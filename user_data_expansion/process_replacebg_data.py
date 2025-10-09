#!/usr/bin/env python3
"""
Process REPLACE-BG data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os
from helpers import get_pump_insulin_types_for_patient, process_s3_data

def generate_replacebg_data():
    """Generate REPLACE-BG user data expansion"""
    # Set up file paths
    base_path = "data/raw/REPLACE-BG Dataset-79f6bdc8-3c51-4736-a39f-c4c0f71d45e5/Data Tables"
    output_path = "data/user_data_expansion/"
    
    print("REPLACE-BG User Data Expansion Pipeline")
    print("=" * 50)
    
    # Step 1: Load roster data
    print("Step 1: Reading participant roster...")
    roster = pd.read_csv(os.path.join(base_path, 'HPtRoster.txt'), delimiter='|')
    print(f"Roster shape: {roster.shape}")
    print("Treatment groups:")
    print(roster['TrtGroup'].value_counts().to_dict())
    
    # Step 2: Load screening data for demographic and device information
    print("\nStep 2: Reading screening data...")
    screening = pd.read_csv(os.path.join(base_path, 'HScreening.txt'), delimiter='|')
    print(f"Screening shape: {screening.shape}")
    print("CGM devices:")
    print(screening['CGMUseDevice'].value_counts(dropna=False).to_dict())
    print("CGM use status:")
    print(screening['CGMUseStatus'].value_counts().to_dict())
    
    # Step 3: Filter completed participants only
    print("\nStep 3: Filtering completed participants...")
    completed_roster = roster[roster['PtStatus'] == 'Completed'].copy()
    print(f"Completed participants: {len(completed_roster)}")
    
    # Step 4: Merge roster with screening data
    print("\nStep 4: Merging roster with screening data...")
    merged_data = completed_roster.merge(screening, on='PtID', how='inner')
    print(f"Merged data shape: {merged_data.shape}")
    
    # Step 5: Create user data expansion dataframe
    print("\nStep 5: Creating user data expansion...")
    user_data_expansion = pd.DataFrame()
    
    # id
    user_data_expansion['id'] = merged_data['PtID']
    user_data_expansion['gender'] = merged_data['Gender']
    user_data_expansion['gender'] = user_data_expansion['gender'].map({'M': 'Male', 'F': 'Female'})

    # Step 5.1: Load device uploads data to determine insulin delivery devices
    print("\nStep 5.1: Reading device uploads data...")
    device_file = os.path.join(base_path, 'HDeviceUploads.txt')
    device_data = pd.read_csv(device_file, delimiter='|')
    print(f"Device data shape: {device_data.shape}")
    print(f"Device data columns: {device_data.columns.tolist()}")
    print("Device types:")
    print(device_data['DeviceType'].value_counts(dropna=False).to_dict())
    
    # Extract insulin pump devices for each patient
    def get_insulin_delivery_device(ptid):
        patient_devices = device_data[device_data['PtId'] == ptid]
        if patient_devices.empty:
            return np.nan
        
        # Look for insulin pump devices
        insulin_pumps = patient_devices[
            patient_devices['DeviceType'].str.contains('insulin-pump', case=False, na=False)
        ]
        
        if insulin_pumps.empty:
            return np.nan

        device_map = {
            "4628": "t:slim G4",
            "5448": "t:slim G4",
            "Tandem t:slim": "t:slim G4",
            "multiple": np.nan
        }

        # Apply mapping before counting
        mapped_models = insulin_pumps['DeviceModel'].replace(device_map)
        device_types = mapped_models.value_counts()
        device_types = device_types.dropna()

        if not device_types.empty:
            return device_types.index[0]  # Return most common device type
        
        return np.nan
    
    # Apply device extraction
    user_data_expansion['insulin_delivery_device'] = merged_data['PtID'].apply(get_insulin_delivery_device)
    
    # Log device extraction results
    device_assigned = user_data_expansion['insulin_delivery_device'].notna().sum()
    print(f"Patients with insulin delivery device detected: {device_assigned}")
    print(f"Patients without device data: {len(user_data_expansion) - device_assigned}")
    print("Detected device types:")
    print(user_data_expansion['insulin_delivery_device'].value_counts(dropna=False).to_dict())
    
    # insulin_delivery_algorithm - REPLACE-BG was not an insulin delivery algorithm study
    # This was a CGM monitoring comparison study
    # Default to standard basal-bolus therapy (most common for T1D at study time)
    user_data_expansion['insulin_delivery_algorithm'] = 'basal-bolus'

    user_data_expansion['cgm_device'] = 'Dexcom G4'
    
    # ethnicity - Map race and ethnicity for REPLACE-BG
    def map_ethnicity_race(row):
        ethnicity = str(row['Ethnicity']) if pd.notna(row['Ethnicity']) else ''
        race = str(row['Race']) if pd.notna(row['Race']) else ''
        
        if ethnicity == 'Hispanic or Latino':
            if race == 'White':
                return 'White, Hispanic/Latino'
            else:
                return 'Hispanic/Latino'
        elif race == 'White':
            return 'White'
        elif race == 'Black or African American':
            return 'Black/African American'
        elif race == 'Asian':
            return 'Asian'
        elif race == 'American Indian or Alaska Native':
            return 'American Indian/Alaska Native'
        elif 'More than one race' in race:
            return 'More than one race'
        else:
            return race if race else 'Unknown'
    
    user_data_expansion['ethnicity'] = merged_data.apply(map_ethnicity_race, axis=1)
    
    # age_of_diagnosis - REPLACE-BG has DiagAge
    user_data_expansion['age_of_diagnosis'] = merged_data['DiagAge'].fillna(np.nan)
    
    # Pregnancy was exclusion criterion
    user_data_expansion['is_pregnant'] = False
    
    # insulin_delivery_modality - REPLACE-BG is a pump study
    user_data_expansion['insulin_delivery_modality'] = 'SAP'

    user_data_expansion['treatment_group'] = merged_data['TrtGroup']

    # Step 6: Load insulin data and determine insulin types
    print("\nStep 6: Processing insulin types from HInsulin.txt...")
    insulin_data = pd.read_csv(os.path.join(base_path, 'HInsulin.txt'), delimiter='|')
    print(f"Insulin data shape: {insulin_data.shape}")
    print(f"Insulin data columns: {insulin_data.columns.tolist()}")
    
    # Apply improved insulin type detection
    insulin_results = []
    for ptid in merged_data['PtID']:
        bolus, basal = get_pump_insulin_types_for_patient(ptid, insulin_data, insulin_name_column='InsName', default=None)
        insulin_results.append({
            'PtID': ptid,
            'insulin_type_bolus': bolus,
            'insulin_type_basal': basal
        })
    
    insulin_df = pd.DataFrame(insulin_results)
    user_data_expansion = user_data_expansion.merge(insulin_df, left_on='id', right_on='PtID', how='left')
    user_data_expansion = user_data_expansion.drop(columns=['PtID'])
    
    # Count how many patients got insulin assignments
    bolus_assigned = user_data_expansion['insulin_type_bolus'].notna().sum()
    basal_assigned = user_data_expansion['insulin_type_basal'].notna().sum()
    print(f"Patients with insulin detected: {bolus_assigned}")
    print(f"Patients without insulin data: {len(user_data_expansion) - bolus_assigned}")
    
    # For pump patients, if no insulin detected, leave as None (np.nan)
    # Only Novolog (Aspart) or Humalog (Lispro) should be assigned, nothing else
    
    print(f"User data expansion created with {len(user_data_expansion)} participants")
    
    print("\nDistributions:")
    print(f"Treatment groups: {merged_data['TrtGroup'].value_counts().to_dict()}")
    print(f"Insulin delivery algorithms: {user_data_expansion['insulin_delivery_algorithm'].value_counts().to_dict()}")
    print(f"Insulin delivery modalities: {user_data_expansion['insulin_delivery_modality'].value_counts().to_dict()}")
    print(f"CGM devices: {user_data_expansion['cgm_device'].value_counts(dropna=False).to_dict()}")
    print(f"Ethnicity: {user_data_expansion['ethnicity'].value_counts().to_dict()}")
    print(f"Age of diagnosis stats: min={user_data_expansion['age_of_diagnosis'].min()}, max={user_data_expansion['age_of_diagnosis'].max()}")
    print(f"Insulin type bolus: {user_data_expansion['insulin_type_bolus'].value_counts(dropna=False).to_dict()}")
    print(f"Insulin type basal: {user_data_expansion['insulin_type_basal'].value_counts(dropna=False).to_dict()}")
    
    return user_data_expansion

def update_replacebg_data(df):
    """Apply standardizations to REPLACE-BG data"""
    print("\n" + "=" * 50)
    print("APPLYING REPLACE-BG DATA STANDARDIZATIONS")
    print("=" * 50)
    
    # Show current null counts
    print("Current null value counts:")
    null_counts = df.isnull().sum()
    for col, count in null_counts.items():
        if count > 0:
            print(f"  {col}: {count} null values")

    # Standardize ethnicity values
    ethnicity_mapping = {
        "Unknown/not reported": None
    }
    
    for old_value, new_value in ethnicity_mapping.items():
        count = (df['ethnicity'] == old_value).sum()
        if count > 0:
            df['ethnicity'] = df['ethnicity'].replace(old_value, new_value)
            print(f"✓ Standardized ethnicity: '{old_value}' → '{new_value}' ({count} records)")
    
    print(f"\nStandardization complete for {len(df)} participants")
    return df

def main():
    """Main processing function"""
    output_path = "data/user_data_expansion/"
    
    # Step 1: Generate REPLACE-BG data
    df = generate_replacebg_data()
    
    # Step 2: Apply standardizations
    df = update_replacebg_data(df)
    
    # Step 3: Save dataframe
    print("\nSaving dataframe...")
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, "ReplaceBG.csv")
    df.to_csv(output_file, index=False)
    
    print(f"✓ Saved REPLACE-BG dataframe to: {output_file}")
    
    # Step 4: Process S3 data if available
    print("\nAttempting S3 data processing...")
    s3_df = process_s3_data(df.copy(), 'ReplaceBG')
    if s3_df is not None:
        print("✓ S3 processing completed successfully")
    else:
        print("⚠ S3 processing failed, continuing with local data only")
    
    # Final summary
    print("\n" + "=" * 70)
    print("REPLACE-BG DATA PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Total participants: {len(df)}")
    print(f"Total columns: {len(df.columns)}")
    print("Dataset ready for analysis!")

    return df

if __name__ == "__main__":
    df = main()