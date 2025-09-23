#!/usr/bin/env python3
"""
Helper functions for insulin data processing
"""

import pandas as pd
import numpy as np
from datetime import datetime

def parse_dates_mixed_format(df, date_column, output_column):
    """
    Parse dates that may be in mixed formats.
    
    Args:
        df: DataFrame containing the date column
        date_column: Name of the column containing dates to parse
        output_column: Name of the output column for parsed dates
    
    Returns:
        DataFrame with new parsed date column
    """
    df = df.copy()
    
    def parse_single_date(date_str):
        if pd.isna(date_str) or date_str == '':
            return pd.NaT
        
        # Try common date formats
        formats = [
            '%Y-%m-%d',
            '%m/%d/%Y',
            '%d/%m/%Y',
            '%Y-%m-%d %H:%M:%S',
            '%m/%d/%Y %H:%M:%S'
        ]
        
        for fmt in formats:
            try:
                return pd.to_datetime(date_str, format=fmt)
            except (ValueError, TypeError):
                continue
        
        # Try pandas default parsing as fallback
        try:
            return pd.to_datetime(date_str)
        except:
            return pd.NaT
    
    df[output_column] = df[date_column].apply(parse_single_date)
    return df

def prioritize_insulin_choice(subject_id, insulin_data_dict):
    """
    Prioritize between multiple insulin types when available.
    Priority: InsRoute == "Pump" > valid start/end dates > last available
    
    Args:
        subject_id: Subject identifier
        insulin_data_dict: Dictionary mapping insulin names to their data rows
    
    Returns:
        String: chosen insulin name
    """
    try:
        # Parse dates for all insulin types
        for insulin_name, df_rows in insulin_data_dict.items():
            if not df_rows.empty:
                # Parse start dates if available
                if 'InsTypeStartDt' in df_rows.columns:
                    df_rows = parse_dates_mixed_format(df_rows, 'InsTypeStartDt', 'start_date_parsed')
                
                # Parse stop dates if available  
                if 'InsTypeStopDt' in df_rows.columns:
                    df_rows = parse_dates_mixed_format(df_rows, 'InsTypeStopDt', 'stop_date_parsed')
                
                # Update the dictionary with parsed data
                insulin_data_dict[insulin_name] = df_rows
        
        # Priority evaluation function
        def evaluate_insulin_priority(insulin_name, df_rows):
            # Priority 1: InsRoute == "Pump" (should already be filtered)
            has_pump_route = (df_rows['InsRoute'] == 'Pump').any()

            # Priority 2: Valid start/end dates
            has_valid_dates = False
            if 'start_date_parsed' in df_rows.columns and 'stop_date_parsed' in df_rows.columns:
                has_valid_dates = (
                    df_rows['start_date_parsed'].notna() & 
                    df_rows['stop_date_parsed'].notna()
                ).any()
            
            # Priority 3: Last available (most recent start date)
            last_available_score = 0
            if 'start_date_parsed' in df_rows.columns:
                valid_start_dates = df_rows['start_date_parsed'].dropna()
                if not valid_start_dates.empty:
                    last_available_score = valid_start_dates.max().timestamp()
            
            return (
                has_pump_route,
                has_valid_dates, 
                last_available_score
            )
        
        # Evaluate all insulin types
        insulin_scores = {}
        for insulin_name, df_rows in insulin_data_dict.items():
            insulin_scores[insulin_name] = evaluate_insulin_priority(insulin_name, df_rows)
        
        # Sort by priority (descending order)
        sorted_insulins = sorted(
            insulin_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Select the highest priority insulin
        chosen_insulin_name = sorted_insulins[0][0]
        chosen_score = sorted_insulins[0][1]
        
        # Log the decision reasoning
        priority_reasons = []
        if chosen_score[0]:  # Pump route
            priority_reasons.append("InsRoute=Pump")
        if chosen_score[1]:  # Valid dates
            priority_reasons.append("valid start/end dates")
        if chosen_score[2] > 0:  # Has some date info
            priority_reasons.append("last available")
        
        reason = " + ".join(priority_reasons) if priority_reasons else "default selection"
        print(f"Subject {subject_id}: Chose {chosen_insulin_name} based on: {reason}")
        
        # Check if there were ties and log
        ties = [name for name, score in sorted_insulins if score == chosen_score]
        if len(ties) > 1:
            print(f"Subject {subject_id}: Tie between {', '.join(ties)}, selected {chosen_insulin_name}")
        
        return chosen_insulin_name
        
    except Exception as e:
        print(f"Error prioritizing insulin for subject {subject_id}: {e}")
        # Return first available insulin as fallback
        if insulin_data_dict:
            return list(insulin_data_dict.keys())[0]
        return None