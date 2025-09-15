#!/usr/bin/env python3
"""
Process IOBP2 data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os

def generate_iobp2_data():
    """Generate IOBP2 user data expansion"""
    # Set up file paths
    base_path = "data/raw/IOBP2 RCT Public Dataset/Data Tables"
    output_path = "data/user_data_expansion/"
    
    print("IOBP2 User Data Expansion Pipeline")
    print("=" * 50)
    
    # Step 1: Load roster data
    print("Step 1: Reading participant roster...")
    roster = pd.read_csv(os.path.join(base_path, 'IOBP2PtRoster.txt'), delimiter='|')
    print(f"Roster shape: {roster.shape}")
    print("Treatment groups:")
    print(roster['TrtGroup'].value_counts().to_dict())
    
    # Step 2: Load screening data for device information
    print("\nStep 2: Reading screening data...")
    screening = pd.read_csv(os.path.join(base_path, 'IOBP2DiabScreening.txt'), delimiter='|')
    print(f"Screening shape: {screening.shape}")
    print("Unique pump types:")
    print(screening['PumpType'].value_counts().to_dict())
    
    # Step 3: Filter completed participants only
    print("\nStep 3: Filtering completed participants...")
    completed_roster = roster[roster['RCTPtStatus'] == 'Completed'].copy()
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
    
    # insulin_delivery_device - Map pump types
    def map_insulin_delivery_device(pump_type):
        if pd.isna(pump_type):
            return 'Unknown'
        
        pump_str = str(pump_type).strip()
        
        if 'OmniPod' in pump_str:
            return 'OmniPod'
        elif 'Tandem' in pump_str:
            if 'Control:IQ' in pump_str or 'Control-IQ' in pump_str:
                return 't:slim X2'
            elif 'Basal:IQ' in pump_str or 'Basal-IQ' in pump_str:
                return 't:slim X2'
            elif 'X2' in pump_str:
                return 't:slim X2'
            else:
                return 't:slim'
        elif 'Medtronic' in pump_str:
            if '630G' in pump_str:
                return 'MiniMed 630G'
            elif '530G' in pump_str or '551' in pump_str:
                return 'MiniMed 530G'
            else:
                return 'MiniMed'
        elif 'Animas' in pump_str:
            return 'Animas One Touch Ping'
        else:
            return pump_str
    
    user_data_expansion['insulin_delivery_device'] = merged_data['PumpType'].apply(map_insulin_delivery_device)
    
    # insulin_delivery_algorithm - Map based on treatment group and device
    def map_insulin_delivery_algorithm(trt_group, device):
        if trt_group == 'Control':
            return 'basal-bolus'
        elif trt_group in ['BP', 'BPFiasp']:
            # Bionic Pancreas used automated insulin delivery
            return 'Bionic Pancreas'
        else:
            # Default based on device
            if 'Control-IQ' in str(device):
                return 'Control-IQ'
            elif 'Basal-IQ' in str(device):
                return 'Basal-IQ'
            else:
                return 'basal-bolus'
    
    user_data_expansion['insulin_delivery_algorithm'] = merged_data.apply(
        lambda x: map_insulin_delivery_algorithm(x['TrtGroup'], x['PumpType']), axis=1
    )
    
    # cgm_device - Map CGM devices
    def map_cgm_device(cgm_device):
        if pd.isna(cgm_device):
            return 'Dexcom G6'  # Default for IOBP2 timeframe (2019-2021)
        elif 'Dexcom' in str(cgm_device):
            return 'Dexcom G6'  # IOBP2 used Dexcom G6 during study period
        else:
            return str(cgm_device)
    
    user_data_expansion['cgm_device'] = merged_data['CGMUseDevice'].apply(map_cgm_device)
    
    # ethnicity - Combine ethnicity and race
    def combine_ethnicity_race(row):
        ethnicity = str(row['Ethnicity']) if pd.notna(row['Ethnicity']) else ''
        race = str(row['Race']) if pd.notna(row['Race']) else ''
        
        if ethnicity == 'Hispanic or Latino':
            return 'Hispanic/Latino'
        elif race == 'White':
            return 'White'
        elif race == 'Black/African American':
            return 'Black/African American'
        elif race == 'Asian':
            return 'Asian'
        elif race == 'More than one race':
            return 'More than one race'
        else:
            return race if race else 'Unknown'
    
    user_data_expansion['ethnicity'] = merged_data.apply(combine_ethnicity_race, axis=1)
    
    # age_of_diagnosis - Not available in IOBP2, set to NaN
    user_data_expansion['age_of_diagnosis'] = np.nan
    
    # is_pregnant - Not specified, default to False
    user_data_expansion['is_pregnant'] = False
    
    # insulin_delivery_modality - Based on algorithm
    def map_insulin_delivery_modality(algorithm):
        if algorithm == 'Bionic Pancreas':
            return 'AID'  # Automated Insulin Delivery
        elif algorithm in ['basal-bolus', 'Control-IQ', 'Basal-IQ']:
            return 'CSII'  # Continuous Subcutaneous Insulin Infusion
        else:
            return 'CSII'
    
    user_data_expansion['insulin_delivery_modality'] = user_data_expansion['insulin_delivery_algorithm'].apply(map_insulin_delivery_modality)
    
    # insulin_type_bolus and insulin_type_basal - Use common insulin for IOBP2 era
    user_data_expansion['insulin_type_bolus'] = 'Novolog (Aspart)'
    user_data_expansion['insulin_type_basal'] = 'Novolog (Aspart)'  # Same for pump users
    
    print(f"User data expansion created with {len(user_data_expansion)} participants")
    
    print("\nDistributions:")
    print(f"Treatment groups: {merged_data['TrtGroup'].value_counts().to_dict()}")
    print(f"Insulin delivery devices: {user_data_expansion['insulin_delivery_device'].value_counts().to_dict()}")
    print(f"Insulin delivery algorithms: {user_data_expansion['insulin_delivery_algorithm'].value_counts().to_dict()}")
    print(f"CGM devices: {user_data_expansion['cgm_device'].value_counts().to_dict()}")
    print(f"Ethnicity: {user_data_expansion['ethnicity'].value_counts().to_dict()}")
    
    return user_data_expansion

def update_iobp2_data(df):
    """Apply standardizations to IOBP2 data"""
    print("\n" + "=" * 50)
    print("APPLYING IOBP2 DATA STANDARDIZATIONS")
    print("=" * 50)
    
    # Show current null counts
    print("Current null value counts:")
    null_counts = df.isnull().sum()
    for col, count in null_counts.items():
        if count > 0:
            print(f"  {col}: {count} null values")
    
    # Fill any null values in key columns
    algorithm_nulls = df['insulin_delivery_algorithm'].isnull().sum()
    if algorithm_nulls > 0:
        df['insulin_delivery_algorithm'] = df['insulin_delivery_algorithm'].fillna('basal-bolus')
        print(f"✓ Filled {algorithm_nulls} null values in insulin_delivery_algorithm with 'basal-bolus'")
    
    modality_nulls = df['insulin_delivery_modality'].isnull().sum()
    if modality_nulls > 0:
        df['insulin_delivery_modality'] = df['insulin_delivery_modality'].fillna('CSII')
        print(f"✓ Filled {modality_nulls} null values in insulin_delivery_modality with 'CSII'")
    
    device_nulls = df['insulin_delivery_device'].isnull().sum()
    if device_nulls > 0:
        df['insulin_delivery_device'] = df['insulin_delivery_device'].fillna('Unknown')
        print(f"✓ Filled {device_nulls} null values in insulin_delivery_device with 'Unknown'")
    
    print(f"\nStandardization complete for {len(df)} participants")
    return df

def main():
    """Main processing function"""
    output_path = "data/user_data_expansion/"
    
    # Step 1: Generate IOBP2 data
    df = generate_iobp2_data()
    
    # Step 2: Apply standardizations
    df = update_iobp2_data(df)
    
    # Step 3: Save dataframe
    print("\nSaving dataframe...")
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, "IOBP2.csv")
    df.to_csv(output_file, index=False)
    
    print(f"✓ Saved IOBP2 dataframe to: {output_file}")
    
    # Final summary
    print("\n" + "=" * 70)
    print("IOBP2 DATA PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Total participants: {len(df)}")
    print(f"Total columns: {len(df.columns)}")
    print("Dataset ready for analysis!")
    
    return df

if __name__ == "__main__":
    df = main()