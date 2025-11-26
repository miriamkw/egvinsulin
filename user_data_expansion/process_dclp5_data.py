#!/usr/bin/env python3
"""
Process DCLP5 data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os
from helpers import parse_dates_mixed_format, get_pump_insulin_types_for_patient, process_s3_data

def get_patient_start_dates(dclp5_data_path):
    """
    Extract the earliest date for each patient from Pump_BolusDelivered.txt
    
    Args:
        dclp5_data_path: Path to DCLP5 data directory
    
    Returns:
        DataFrame with PtID and start_date columns
    """
    try:
        bolus_file = os.path.join(dclp5_data_path, "DCLP5TandemBolus_Completed_Combined_b.txt")
        print(f"Reading bolus delivery data from: {bolus_file}")
        
        # Read the bolus delivery data
        bolus_df = pd.read_csv(bolus_file, delimiter="|")
        print(f"Bolus data shape: {bolus_df.shape}")
        print(f"Bolus data columns: {bolus_df.columns.tolist()}")
        
        date_column = 'DataDtTm'
        print(f"Using date column: {date_column}")
        
        # Parse dates
        bolus_df = parse_dates_mixed_format(bolus_df, date_column, 'parsed_date')
        
        # Filter out rows with invalid dates
        valid_dates_df = bolus_df[bolus_df['parsed_date'].notna()].copy()
        print(f"Valid date records: {len(valid_dates_df)} out of {len(bolus_df)}")
        
        if valid_dates_df.empty:
            print("Warning: No valid dates found in Pump_BolusDelivered.txt")
            return pd.DataFrame(columns=['PtID', 'start_date'])
        
        # Find earliest date for each patient
        earliest_dates = valid_dates_df.groupby('PtID')['parsed_date'].min().reset_index()
        earliest_dates.columns = ['PtID', 'start_date']
        
        print(f"Extracted start dates for {len(earliest_dates)} patients")
        print(f"Date range: {earliest_dates['start_date'].min()} to {earliest_dates['start_date'].max()}")
        
        return earliest_dates
        
    except Exception as e:
        print(f"Error reading Pump_BolusDelivered.txt: {e}")
        return pd.DataFrame(columns=['PtID', 'start_date'])

def generate_dclp5_data():
    """Generate DCLP5 user data expansion following DCLP3 pattern"""
    # Set up file paths
    dclp5_data_path = "data/raw/DCLP5_Dataset_2022-01-20-5e0f3b16-c890-4ace-9e3b-531f3687cf53/"
    output_path = "data/user_data_expansion/"
    
    print("DCLP5 User Data Expansion Pipeline")
    print("=" * 50)
    
    # Step 1: Read roster
    print("Step 1: Reading participant roster...")
    roster_file = os.path.join(dclp5_data_path, "PtRoster.txt")
    roster_df = pd.read_csv(roster_file, delimiter="|")
    print(f"Roster shape: {roster_df.shape}")
    print(f"Columns: {roster_df.columns.tolist()}")
    
    # Step 2: Read insulin data 
    print("\nStep 2: Reading insulin data...")
    insulin_file = os.path.join(dclp5_data_path, "Insulin.txt")
    insulin_df = pd.read_csv(insulin_file, delimiter="|")
    print(f"Insulin data shape: {insulin_df.shape}")
    print(f"Unique delivery routes: {insulin_df['InsRoute'].value_counts().to_dict()}")

    # Step 4: Create base dataframe
    print("\nStep 4: Creating base dataframe...")
    final_df = roster_df[['PtID', 'EnrollDt', 'RandDt', 'trtGroup', 'PtStatus', 'SiteID']].copy()

    # Step 5: Update device specifics
    print("\nStep 5: Updating device specifics...")
    final_df['insulin_delivery_device'] = 't:slim X2'  # Known from the protocol
    final_df['insulin_delivery_algorithm'] = final_df['trtGroup'].map({
        'SC': 'Basal-IQ',
        'CLC': 'Control-IQ'
    })
    
    print(f"Treatment groups: {final_df['trtGroup'].value_counts().to_dict()}")
    print(f"Algorithms: {final_df['insulin_delivery_algorithm'].value_counts().to_dict()}")
    
    # Step 6: Add CGM device
    print("\nStep 6: Adding CGM device information...")
    final_df['cgm_device'] = "Dexcom G6"  # DCLP5 used G6, stated in the protocol
    print(f"CGM device distribution: {final_df['cgm_device'].value_counts(dropna=False).to_dict()}")

    # Step 7: Add ethnicity
    print("\nStep 7: Adding ethnicity information...")
    try:
        screening_file = os.path.join(dclp5_data_path, "DiabScreening.txt")
        screening_df = pd.read_csv(screening_file, delimiter="|")
        ethnicity_data = screening_df[['PtID', 'Ethnicity', 'Race', 'RaceDs']].copy()
        
        def format_ethnicity(row):
            race = row['Race']
            ethnicity = row['Ethnicity'] 
            race_desc = row['RaceDs']
            
            if pd.isna(race) or race == '':
                return np.nan
            
            if race == 'More than one race':
                if pd.notna(race_desc) and race_desc.strip():
                    races = race_desc.replace(' and ', ', ').replace('and ', ', ')
                    races = races.replace('caucasian', 'White').replace('hatian', 'Haitian')
                    races = races.replace('asian', 'Asian').replace('Spanish', 'Hispanic/Latino')
                    formatted_race = races
                else:
                    formatted_race = 'Multiple races'
            else:
                formatted_race = race
            
            if pd.notna(ethnicity) and ethnicity == 'Hispanic or Latino':
                if 'Hispanic/Latino' not in formatted_race:
                    formatted_race += ', Hispanic/Latino'
            
            return formatted_race
        
        ethnicity_data['formatted_ethnicity'] = ethnicity_data.apply(format_ethnicity, axis=1)
        ethnicity_mapping = ethnicity_data[['PtID', 'formatted_ethnicity']].copy()
        ethnicity_mapping.columns = ['PtID', 'ethnicity']
        
        final_df = final_df.merge(ethnicity_mapping, on='PtID', how='left')
        
        print(f"Ethnicity categories: {len(final_df['ethnicity'].unique())} unique values")

        final_df = final_df.merge(screening_df[['PtID', 'Gender']], on='PtID', how='left')
        final_df.rename(columns={'Gender': 'gender'}, inplace=True)
        final_df['gender'] = final_df['gender'].map({'M': 'Male', 'F': 'Female'})

    except Exception as e:
        print(f"Error reading ethnicity data: {e}")
        final_df['ethnicity'] = np.nan

    """
    # Step 7.5: Add start_date from pump bolus data
    print("\nStep 7.5: Adding start_date from pump bolus delivery data...")
    try:
        start_dates_df = get_patient_start_dates(dclp5_data_path)
        if not start_dates_df.empty:
            final_df = final_df.merge(start_dates_df, on='PtID', how='left')
            
            # Convert to date format (remove time component if present)
            final_df['start_date'] = pd.to_datetime(final_df['start_date']).dt.date
            
            print(f"Start dates added for {final_df['start_date'].notna().sum()} patients")
        else:
            final_df['start_date'] = np.nan
            print("No start dates could be extracted")
    except Exception as e:
        print(f"Error adding start dates: {e}")
        final_df['start_date'] = np.nan
    """

    # Step 8: Add age of diagnosis
    print("\nStep 8: Adding age of diagnosis...")
    try:
        diagnosis_age_data = screening_df[['PtID', 'DiagAge']].copy()
        diagnosis_age_data.columns = ['PtID', 'age_of_diagnosis']
        final_df = final_df.merge(diagnosis_age_data, on='PtID', how='left')
        
        print(f"Age of diagnosis range: {final_df['age_of_diagnosis'].min()}-{final_df['age_of_diagnosis'].max()} years")
        
    except Exception as e:
        print(f"Error reading age of diagnosis: {e}")
        final_df['age_of_diagnosis'] = np.nan
    
    # Step 9: Add pregnancy status
    print("\nStep 9: Adding pregnancy status...")
    final_df['is_pregnant'] = False  # Pediatric study - pregnancy exclusion
    
    # Step 10: Add delivery modality  
    print("\nStep 10: Adding delivery modality...")
    final_df['insulin_delivery_modality'] = final_df['trtGroup'].map({
        'SC': 'SAP',
        'CLC': 'AID'
    })
    
    # Step 11: Add insulin types (pump-only) using improved helper function
    print("\nStep 11: Adding insulin types...")
    
    pump_insulin_results = []
    for ptid in final_df['PtID']:
        bolus, basal = get_pump_insulin_types_for_patient(ptid, insulin_df, insulin_name_column='ParentInsulinListID', default='Humalog (Lispro) or Novolog (Aspart)')
        pump_insulin_results.append({
            'PtID': ptid,
            'insulin_type_bolus': bolus,
            'insulin_type_basal': basal
        })
    
    pump_insulin_df = pd.DataFrame(pump_insulin_results)
    final_df = final_df.merge(pump_insulin_df, on='PtID', how='left')
    
    # For pump patients, use same insulin for bolus and basal if basal is missing
    final_df.loc[
        (final_df['insulin_delivery_device'] == 't:slim X2') & 
        (final_df['insulin_type_basal'].isna()) & 
        (final_df['insulin_type_bolus'].notna()),
        'insulin_type_basal'
    ] = final_df.loc[
        (final_df['insulin_delivery_device'] == 't:slim X2') & 
        (final_df['insulin_type_basal'].isna()) & 
        (final_df['insulin_type_bolus'].notna()),
        'insulin_type_bolus'
    ]
    
    print(f"Bolus insulin types: {final_df['insulin_type_bolus'].value_counts(dropna=False).to_dict()}")
    print(f"Basal insulin types: {final_df['insulin_type_basal'].value_counts(dropna=False).to_dict()}")
    
    # Step 12: Final cleanup
    print("\nStep 12: Final cleanup...")
    final_df = final_df.rename(columns={'PtID': 'id', 'trtGroup': 'treatment_group', 'RandDt': 'randomization_date'})
    columns_to_drop = ['EnrollDt', 'PtStatus', 'SiteID']
    final_df = final_df.drop(columns=columns_to_drop)
    
    print(f"Final shape: {final_df.shape}")
    print(f"Final columns: {final_df.columns.tolist()}")
    
    return final_df


def process_extension_phase_logic(df):
    roster_df = pd.read_csv('data/raw/DCLP5_Dataset_2022-01-20-5e0f3b16-c890-4ace-9e3b-531f3687cf53/PtRoster.txt',
                            sep='|')
    ext_phase_df = pd.read_csv('data/raw/DCLP5_Dataset_2022-01-20-5e0f3b16-c890-4ace-9e3b-531f3687cf53/16WkCTV.txt',
                               sep='|')

    # Convert datetime columns
    df['date'] = pd.to_datetime(df['date'])
    roster_df['Phase2StartDt'] = pd.to_datetime(roster_df['Phase2StartDt'])

    # Group by unique patient ID
    for patient_id, patient_data in df.groupby('id'):
        # Check if patient has Basal-IQ
        if 'Basal-IQ' in patient_data['insulin_delivery_algorithm'].values:
            # Calculate days span for CGM data
            cgm_dates = patient_data['date']
            days_span = (cgm_dates.max() - cgm_dates.min()).days

            # Get the insulin delivery algorithm for printing
            expansion_row = patient_data.iloc[0]  # Get first row for algorithm info
            print(
                f"Patient {patient_id}: {days_span} days between first and last CGM value. {expansion_row['insulin_delivery_algorithm']}")

            # Check ExtPhaseCont status
            ext_phase_info = ext_phase_df[ext_phase_df['PtID'] == patient_id]
            if not ext_phase_info.empty:
                ext_phase_cont = ext_phase_info['ExtPhaseCont'].iloc[0]
                print(f"  Extension Phase Continuation: {ext_phase_cont}")
            else:
                print(f"  Extension Phase Continuation: Not found")

            # Look up Phase2StartDt from roster
            phase2_info = roster_df[roster_df['PtID'] == patient_id]

            if not phase2_info.empty and pd.notna(phase2_info['Phase2StartDt'].iloc[0]):
                phase2_start = phase2_info['Phase2StartDt'].iloc[0]

                # Calculate days before and after Phase2StartDt
                days_before = (phase2_start - cgm_dates.min()).days
                days_after = (cgm_dates.max() - phase2_start).days

                print(f"  Phase 2 start date: {phase2_start.date()}")
                print(f"  Days before Phase 2 start: {days_before}")
                print(f"  Days after Phase 2 start: {days_after}")

                # Update insulin delivery algorithm and modality from Phase2StartDt onwards
                phase2_mask = (df['id'] == patient_id) & (df['date'] >= phase2_start)
                df.loc[phase2_mask, 'insulin_delivery_algorithm'] = 'Control-IQ'
                df.loc[phase2_mask, 'insulin_delivery_modality'] = 'AID'

                updated_count = phase2_mask.sum()
                print(f"  Updated {updated_count} rows to Control-IQ/AID")

            else:
                print(f"  Phase 2 start date not available for patient {patient_id}")

            print()  # Empty line for readability
    return df


def update_dclp5_data(df):
    """Apply standardizations to DCLP5 data"""
    print("\n" + "=" * 50)
    print("APPLYING DCLP5 DATA STANDARDIZATIONS")
    print("=" * 50)
    
    # Show current null counts
    print("\nCurrent null value counts:")
    null_counts = df.isnull().sum()
    for col, count in null_counts.items():
        if count > 0:
            print(f"  {col}: {count} null values")

    # 3. Standardize ethnicity categories
    print("\n3. Standardizing ethnicity categories...")
    print("   Current ethnicity distribution:")
    current_ethnicities = df['ethnicity'].value_counts(dropna=False)
    for ethnicity, count in current_ethnicities.items():
        print(f"     {ethnicity}: {count}")
    
    # Define ethnicity mappings
    ethnicity_mappings = {
        "White, Asian mixed": "White, Asian",
        "Caucasion, Latino, Hispanic/Latino": "White, Hispanic/Latino", 
        "Unknown/not reported, Hispanic/Latino": "Hispanic/Latino",
        "CaucAsian, Asian": "White, Asian",
        "Asian, CaucAsian": "White, Asian"
    }
    
    print(f"\n   Applying ethnicity mappings:")
    for old_value, new_value in ethnicity_mappings.items():
        count = (df['ethnicity'] == old_value).sum()
        if count > 0:
            df['ethnicity'] = df['ethnicity'].replace(old_value, new_value)
            print(f"     '{old_value}' → '{new_value}' ({count} records)")
    
    # Show updated ethnicity distribution
    print("\n   Updated ethnicity distribution:")
    updated_ethnicities = df['ethnicity'].value_counts(dropna=False)
    for ethnicity, count in updated_ethnicities.items():
        print(f"     {ethnicity}: {count}")
    
    # Final verification - check for any remaining null values
    print("\n4. Final verification...")
    final_null_counts = df.isnull().sum()
    remaining_nulls = final_null_counts[final_null_counts > 0]
    
    if len(remaining_nulls) > 0:
        print("   Remaining null values:")
        for col, count in remaining_nulls.items():
            print(f"     {col}: {count} null values")
    else:
        print("   ✓ No remaining null values in key columns")
    
    # Show final algorithm and modality distributions
    print("\n   Final distributions:")
    print("   insulin_delivery_algorithm:")
    for value, count in df['insulin_delivery_algorithm'].value_counts().items():
        print(f"     {value}: {count}")
    
    print("   insulin_delivery_modality:")
    for value, count in df['insulin_delivery_modality'].value_counts().items():
        print(f"     {value}: {count}")
    
    print(f"\nSTANDARDIZATION SUMMARY:")
    print(f"✓ Standardized {len(ethnicity_mappings)} ethnicity categories")
    print(f"✓ Final shape: {df.shape}")
    
    return df

def main():
    """Main processing function"""
    output_path = "data/user_data_expansion/"
    
    # Step 1: Generate DCLP5 data
    df = generate_dclp5_data()
    
    # Step 2: Apply standardizations
    df = update_dclp5_data(df)
    
    # Step 3: Save final dataframe
    print("\nSaving final dataframe...")
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, "DCLP5.csv")
    df.to_csv(output_file, index=False)
    
    print(f"✓ Saved DCLP5 dataframe to: {output_file}")

    df_resampled = pd.read_csv('data/resampled/DCLP5.csv')
    df_resampled['insulin'] = df_resampled['bolus'].fillna(0) + df_resampled['basal']
    
    # Step 4: Process S3 data if available
    print("\nAttempting S3 data processing...")
    s3_df = process_s3_data(df.copy(), 'DCLP5', df=df_resampled)
    if s3_df is not None:
        print("✓ S3 processing completed successfully")
    else:
        print("⚠ S3 processing failed, continuing with local data only")

    print("\nProcessing extension phase insulin delivery algorithm-logic")
    s3_df = process_extension_phase_logic(s3_df)
    output_file = f"DCLP5.csv"
    s3_df.to_csv(output_file, index=False)

    # Final summary
    print("\n" + "=" * 70)
    print("DCLP5 DATA PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Total participants: {len(df)}")
    print(f"Total columns: {len(df.columns)}")
    print("Dataset ready for analysis!")
    
    return df

if __name__ == "__main__":
    df = main()