#!/usr/bin/env python3
"""
Helper functions for insulin data processing
"""

import pandas as pd
import numpy as np
from datetime import datetime
import boto3
from io import StringIO
import os

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

def get_pump_insulin_types_for_patient(ptid, insulin_data):
    """
    Improved insulin type detection for pump patients.
    Determines whether patient used Aspart or Lispro and sets same for both bolus and basal.
    
    Args:
        ptid: Patient ID
        insulin_data: DataFrame containing insulin data
    
    Returns:
        tuple: (bolus_insulin, basal_insulin) - same insulin for both in pump patients
    """
    try:
        # Filter to only pump insulin records for this patient
        patient_pump_insulin = insulin_data[
            (insulin_data['PtID'] == ptid) & 
            (insulin_data['InsRoute'] == 'Pump')
        ].copy()
        
        if patient_pump_insulin.empty:
            print(f"No pump insulin data found for patient {ptid}")
            return np.nan, np.nan

        # Search for Aspart and Lispro specifically
        aspart_rows = patient_pump_insulin[
            patient_pump_insulin['ParentInsulinListID'].str.contains(
                'Aspart', case=False, na=False
            )
        ]
        lispro_rows = patient_pump_insulin[
            patient_pump_insulin['ParentInsulinListID'].str.contains(
                'Lispro|Humalog', case=False, na=False  
            )
        ]
        
        has_aspart = not aspart_rows.empty
        has_lispro = not lispro_rows.empty
        
        # Log available options
        available_options = []
        if has_aspart:
            available_options.append("Aspart")
        if has_lispro:
            available_options.append("Lispro")
        
        if len(available_options) > 1:
            print(f"Patient {ptid}: Has multiple insulin options: {', '.join(available_options)}")
        
        # Determine which insulin to use
        if len(available_options) > 1:
            # Multiple available - use prioritization logic
            insulin_data_dict = {}
            if has_aspart:
                insulin_data_dict['Novolog (Aspart)'] = aspart_rows
            if has_lispro:
                insulin_data_dict['Humalog (Lispro)'] = lispro_rows
            
            chosen_insulin = prioritize_insulin_choice(ptid, insulin_data_dict)
        elif has_aspart:
            # Only Aspart available
            chosen_insulin = 'Novolog (Aspart)'
            print(f"Patient {ptid}: Only Aspart available, using Novolog (Aspart)")
        elif has_lispro:
            # Only Lispro available  
            chosen_insulin = 'Humalog (Lispro)'
            print(f"Patient {ptid}: Only Lispro available, using Humalog (Lispro)")
        else:
            print(f"Warning: No Aspart or Lispro insulin found for pump patient {ptid}")
            return np.nan, np.nan
        
        print(f"Patient {ptid}: Assigned insulin type '{chosen_insulin}' for both bolus and basal")
        
        # Return the same insulin for both bolus and basal (pump patients use same insulin)
        return chosen_insulin, chosen_insulin
        
    except Exception as e:
        print(f"Error processing insulin data for patient {ptid}: {e}")
        return np.nan, np.nan

def process_s3_data(df_expansion_data_copy, dataset_name, bucket_name='replica-general-data-repository'):
    """
    Process dataset data with S3 integration - generalized version
    
    Args:
        df_expansion_data_copy: DataFrame containing local expansion data to merge
        dataset_name: Name of the dataset (e.g., 'DCLP3', 'DCLP5')
        bucket_name: S3 bucket name (default: 'replica-general-data-repository')
    
    Returns:
        DataFrame: Merged and processed dataframe, or None if processing fails
    """
    print("\n" + "=" * 50)
    print(f"S3 DATA PROCESSING PIPELINE - {dataset_name}")
    print("=" * 50)
    
    file_name = f'{dataset_name}.csv'
    
    try:
        # Step 1: Load from S3
        print("Step 1: Loading data from S3...")
        obj_key = f'processed_data_final_expanded/{file_name}'
        s3 = boto3.client("s3")
        obj_response = s3.get_object(Bucket=bucket_name, Key=obj_key)
        content = obj_response["Body"].read().decode("utf-8")
        df = pd.read_csv(StringIO(content), low_memory=False)
        print(f"✓ Successfully loaded S3 data: {df.shape}")

        # Step 2: Overwrite matching columns with expansion data (block sparse per id)
        print("\nStep 2: Merging expansion data with S3 data...")
        matching_columns = [col for col in df_expansion_data_copy.columns if col in df.columns]
        print(f"Found {len(matching_columns)} matching columns: {matching_columns}")
        
        # Create a mapping of id to expansion data for efficient lookup
        expansion_dict = df_expansion_data_copy.set_index('id').to_dict('index')
        
        # Update matching columns for each id that exists in both datasets
        updated_count = 0
        for idx, row in df.iterrows():
            patient_id = row['id']
            if patient_id in expansion_dict:
                expansion_row = expansion_dict[patient_id]
                for col in matching_columns:
                    if col != 'id' and col in expansion_row:
                        # Only update if expansion data has a non-null value
                        expansion_value = expansion_row[col]
                        if pd.notna(expansion_value):
                            df.at[idx, col] = expansion_value
                updated_count += 1
        
        print(f"✓ Updated {updated_count} patient records with expansion data")

        # Step 3: Convert weight/height units
        print("\nStep 3: Converting weight and height units...")
        weight_cols = [col for col in df.columns if 'weight' in col.lower()]
        height_cols = [col for col in df.columns if 'height' in col.lower()]
        
        for weight_col in weight_cols:
            if weight_col in df.columns and df[weight_col].mean() < 120:  # Likely kg
                df[weight_col] = df[weight_col] * 2.20462
                print(f"✓ Converted {weight_col} from kg to lbs")
        
        for height_col in height_cols:
            if height_col in df.columns and df[height_col].mean() > 50:  # Likely cm
                df[height_col] = df[height_col] / 30.48
                print(f"✓ Converted {height_col} from cm to feet")

        # Step 4: Save the updated df locally
        print("\nStep 4: Saving updated dataframe locally...")
        output_file = f"{dataset_name}_s3_merged.csv"
        df.to_csv(output_file, index=False)
        print(f"✓ Saved merged S3 dataframe to: {output_file}")
        print(f"  Final merged dataset shape: {df.shape}")

        # Step 5: Analyze updated dataframe with value counts (including NaNs)
        print("\nStep 5: Analyzing merged dataframe...")
        print("Value counts for key categorical columns (including NaNs):")
        
        categorical_columns = [
            'insulin_delivery_device', 'insulin_delivery_algorithm', 'cgm_device',
            'ethnicity', 'insulin_delivery_modality', 'insulin_type_bolus', 'insulin_type_basal'
        ]
        
        for col in categorical_columns:
            if col in df.columns:
                print(f"\n{col}:")
                counts = df[col].value_counts(dropna=False)
                for value, count in counts.items():
                    print(f"  {value}: {count}")
        
        # Summary statistics for numerical columns
        numerical_columns = ['age_of_diagnosis']
        for col in numerical_columns:
            if col in df.columns:
                print(f"\n{col} statistics:")
                print(f"  Count (non-null): {df[col].count()}")
                print(f"  Count (null): {df[col].isna().sum()}")
                if df[col].count() > 0:
                    print(f"  Mean: {df[col].mean():.2f}")
                    print(f"  Min: {df[col].min():.2f}")
                    print(f"  Max: {df[col].max():.2f}")
        
        print(f"\nOverall dataset summary:")
        print(f"  Total rows: {len(df)}")
        print(f"  Total columns: {len(df.columns)}")
        print(f"  Missing values per column:")
        missing_counts = df.isna().sum()
        for col, missing_count in missing_counts.items():
            if missing_count > 0:
                print(f"    {col}: {missing_count}")
        
        return df

    except Exception as e:
        print(f"Error in S3 processing: {e}")
        print("Skipping S3 integration - continuing with local processing only")
        return None