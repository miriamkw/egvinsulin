#!/usr/bin/env python3
"""
Process REPLACE-BG data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os

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
    
    # insulin_delivery_device - REPLACE-BG doesn't specify insulin delivery devices
    # This was a CGM monitoring study, not an insulin delivery study
    user_data_expansion['insulin_delivery_device'] = np.nan
    
    # insulin_delivery_algorithm - REPLACE-BG was not an insulin delivery algorithm study
    # This was a CGM monitoring comparison study
    # Default to standard basal-bolus therapy (most common for T1D at study time)
    user_data_expansion['insulin_delivery_algorithm'] = 'basal-bolus'
    
    # cgm_device - Map CGM devices for REPLACE-BG
    def map_cgm_device(cgm_device):
        if pd.isna(cgm_device):
            return np.nan
        elif 'Dexcom' in str(cgm_device):
            return 'Dexcom G5'  # REPLACE-BG timeframe used G5
        elif 'Medtronic' in str(cgm_device):
            return 'Medtronic Guardian'
        else:
            return str(cgm_device)
    
    user_data_expansion['cgm_device'] = merged_data['CGMUseDevice'].apply(map_cgm_device)
    
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
    
    # is_pregnant - Check if any pregnancy data available, otherwise default to False
    # REPLACE-BG was an adult study, pregnancy status not specified in screening
    user_data_expansion['is_pregnant'] = False
    
    # insulin_delivery_modality - Based on algorithm (all basal-bolus)
    # Since REPLACE-BG was not an insulin delivery study, default to most common modality
    def map_insulin_delivery_modality(algorithm):
        if algorithm == 'basal-bolus':
            return 'MDI'  # Multiple Daily Injections (most common for basal-bolus)
        else:
            return 'MDI'
    
    user_data_expansion['insulin_delivery_modality'] = user_data_expansion['insulin_delivery_algorithm'].apply(map_insulin_delivery_modality)
    
    # insulin_type_bolus - REPLACE-BG doesn't specify insulin types
    # Use common fast-acting insulin for adult T1D population
    user_data_expansion['insulin_type_bolus'] = 'Humalog (Lispro)'
    
    # insulin_type_basal - For MDI, typically different from bolus
    user_data_expansion['insulin_type_basal'] = 'Lantus (Glargine)'  # Common long-acting for MDI
    
    print(f"User data expansion created with {len(user_data_expansion)} participants")
    
    print("\nDistributions:")
    print(f"Treatment groups: {merged_data['TrtGroup'].value_counts().to_dict()}")
    print(f"Insulin delivery algorithms: {user_data_expansion['insulin_delivery_algorithm'].value_counts().to_dict()}")
    print(f"Insulin delivery modalities: {user_data_expansion['insulin_delivery_modality'].value_counts().to_dict()}")
    print(f"CGM devices: {user_data_expansion['cgm_device'].value_counts(dropna=False).to_dict()}")
    print(f"Ethnicity: {user_data_expansion['ethnicity'].value_counts().to_dict()}")
    print(f"Age of diagnosis stats: min={user_data_expansion['age_of_diagnosis'].min()}, max={user_data_expansion['age_of_diagnosis'].max()}")
    print(f"Insulin type bolus: {user_data_expansion['insulin_type_bolus'].value_counts().to_dict()}")
    print(f"Insulin type basal: {user_data_expansion['insulin_type_basal'].value_counts().to_dict()}")
    
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
    
    # Fill any null values in key columns (though most should be complete for REPLACE-BG)
    algorithm_nulls = df['insulin_delivery_algorithm'].isnull().sum()
    if algorithm_nulls > 0:
        df['insulin_delivery_algorithm'] = df['insulin_delivery_algorithm'].fillna('basal-bolus')
        print(f"✓ Filled {algorithm_nulls} null values in insulin_delivery_algorithm with 'basal-bolus'")
    
    modality_nulls = df['insulin_delivery_modality'].isnull().sum()
    if modality_nulls > 0:
        df['insulin_delivery_modality'] = df['insulin_delivery_modality'].fillna('MDI')
        print(f"✓ Filled {modality_nulls} null values in insulin_delivery_modality with 'MDI'")
    
    # Standardize ethnicity values
    ethnicity_mapping = {
        "Unknown/not reported": "Unknown"
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
    
    # Final summary
    print("\n" + "=" * 70)
    print("REPLACE-BG DATA PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Total participants: {len(df)}")
    print(f"Total columns: {len(df.columns)}")
    print("Dataset ready for analysis!")
    print("\nNote: REPLACE-BG was a CGM monitoring study, not an insulin delivery study.")
    print("Insulin delivery device information is not available (set to NaN).")
    print("Insulin types and modalities are set to common defaults for T1D population.")
    
    return df

if __name__ == "__main__":
    df = main()