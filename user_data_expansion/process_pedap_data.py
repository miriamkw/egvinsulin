#!/usr/bin/env python3
"""
Process PEDAP data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os

def generate_pedap_data():
    """Generate PEDAP user data expansion"""
    # Set up file paths
    base_path = "data/raw/PEDAP Public Dataset - Release 3 - 2024-09-25/Data Files"
    output_path = "data/user_data_expansion/"
    
    print("PEDAP User Data Expansion Pipeline")
    print("=" * 50)
    
    # Step 1: Load roster data
    print("Step 1: Reading participant roster...")
    roster = pd.read_csv(os.path.join(base_path, 'PtRoster.txt'), delimiter='|')
    print(f"Roster shape: {roster.shape}")
    print("Treatment groups:")
    print(roster['TrtGroup'].value_counts().to_dict())
    
    # Step 2: Load screening data for device and demographic information
    print("\nStep 2: Reading screening data...")
    screening = pd.read_csv(os.path.join(base_path, 'PEDAPDiabScreening.txt'), delimiter='|')
    print(f"Screening shape: {screening.shape}")
    print("Unique pump types:")
    print(screening['PumpType'].value_counts().to_dict())
    print("CGM devices:")
    print(screening['CGMUseDevice'].value_counts().to_dict())
    
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
    
    user_data_expansion['insulin_delivery_device'] = 't:slim X2'
    user_data_expansion['insulin_delivery_algorithm'] = 'Control-IQ'
    user_data_expansion['cgm_device'] = 'Dexcom G6'
    
    # ethnicity - Combine ethnicity and race like DCLP3
    def combine_ethnicity_race(row):
        ethnicity = str(row['Ethnicity']) if pd.notna(row['Ethnicity']) else ''
        race = str(row['Race']) if pd.notna(row['Race']) else ''
        
        if ethnicity == 'Hispanic or Latino':
            if race == 'White':
                return 'White, Hispanic/Latino'
            elif race == 'More than one race':
                return 'Hispanic/Latino, More than one race'
            else:
                return 'Hispanic/Latino'
        elif race == 'White':
            return 'White'
        elif race == 'Black/African American':
            return 'Black/African American'
        elif race == 'Asian':
            return 'Asian'
        elif race == 'More than one race':
            return 'More than one race'
        elif race == 'American Indian/Alaska Native':
            return 'American Indian/Alaska Native'
        else:
            return race if race else 'Unknown'
    
    user_data_expansion['ethnicity'] = merged_data.apply(combine_ethnicity_race, axis=1)
    
    # age_of_diagnosis - PEDAP has DiagAge (age at diagnosis)
    user_data_expansion['age_of_diagnosis'] = merged_data['DiagAge'].fillna(np.nan)
    
    # is_pregnant - Always False for pediatric population (ages 2-5)
    user_data_expansion['is_pregnant'] = False
            
    user_data_expansion['insulin_delivery_modality'] = 'AID'
    
    # Step 6: Load insulin data for insulin types
    print("\nStep 6: Processing insulin types...")
    insulin_data = pd.read_csv(os.path.join(base_path, 'PEDAPInsulin.txt'), delimiter='|')
    print(f"Insulin data shape: {insulin_data.shape}")
    print("Insulin type start distribution:")
    print(insulin_data['InsTypeStart'].value_counts().to_dict())
    
    def get_insulin_type(pt_id, trt_group, insulin_df, insulin_category='bolus'):
        patient_insulins = insulin_df[insulin_df['PtID'] == pt_id].copy()
        
        if patient_insulins.empty:
            return np.nan
        
        # Priority 1: Started after enrollment (for any treatment group)
        started_after = patient_insulins[patient_insulins['InsTypeStart'] == 'Started after enrollment']
        
        if not started_after.empty:
            # Filter for bolus vs basal insulins
            if insulin_category == 'bolus':
                # Fast-acting insulins (bolus)
                bolus_insulins = started_after[started_after['InsulinName'].str.contains(
                    'Humalog|Novolog|Fiasp|Apidra|Lispro|Aspart', case=False, na=False)]
                if not bolus_insulins.empty:
                    return bolus_insulins.iloc[0]['InsulinName']
            else:  # basal
                # Long-acting insulins (basal) or pump (same as bolus)
                basal_insulins = started_after[started_after['InsulinName'].str.contains(
                    'Lantus|Levemir|Tresiba|Glargine|Detemir|Degludec', case=False, na=False)]
                if not basal_insulins.empty:
                    return basal_insulins.iloc[0]['InsulinName']
                # For pumps, basal = bolus insulin
                elif started_after[started_after['InsRoute'] == 'Pump'].shape[0] > 0:
                    pump_insulin = started_after[started_after['InsRoute'] == 'Pump'].iloc[0]['InsulinName']
                    return pump_insulin
        
        # Priority 2: In use at time of enrollment (for ANY treatment group)
        in_use = patient_insulins[patient_insulins['InsTypeStart'] == 'In use at time of enrollment']
        
        if not in_use.empty:
            if insulin_category == 'bolus':
                bolus_insulins = in_use[in_use['InsulinName'].str.contains(
                    'Humalog|Novolog|Fiasp|Apidra|Lispro|Aspart', case=False, na=False)]
                if not bolus_insulins.empty:
                    return bolus_insulins.iloc[0]['InsulinName']
            else:  # basal
                basal_insulins = in_use[in_use['InsulinName'].str.contains(
                    'Lantus|Levemir|Tresiba|Glargine|Detemir|Degludec', case=False, na=False)]
                if not basal_insulins.empty:
                    return basal_insulins.iloc[0]['InsulinName']
                # For pumps, basal = bolus insulin
                elif in_use[in_use['InsRoute'] == 'Pump'].shape[0] > 0:
                    pump_insulin = in_use[in_use['InsRoute'] == 'Pump'].iloc[0]['InsulinName']
                    return pump_insulin
        
        return np.nan
    
    # Apply the insulin mapping
    user_data_expansion['insulin_type_bolus'] = merged_data.apply(
        lambda x: get_insulin_type(x['PtID'], x['TrtGroup'], insulin_data, 'bolus'), axis=1
    )
    
    user_data_expansion['insulin_type_basal'] = merged_data.apply(
        lambda x: get_insulin_type(x['PtID'], x['TrtGroup'], insulin_data, 'basal'), axis=1
    )
    
    # Step 7: Fix insulin types for pump users
    print("\nStep 7: Correcting insulin types for pump users...")
    
    # For pump users (SAP/AID), basal insulin should match bolus insulin
    def fix_pump_insulin_types(row):
        modality = row['insulin_delivery_modality']
        bolus = row['insulin_type_bolus']
        basal = row['insulin_type_basal']
        
        # For pump users (SAP/AID), basal should equal bolus
        if modality in ['SAP', 'AID']:
            # If we have bolus but different basal, use bolus for basal
            if pd.notna(bolus) and pd.notna(basal) and bolus != basal:
                # Check if basal is a long-acting insulin (indicates MDI, not pump)
                if any(long_acting in str(basal).lower() for long_acting in ['lantus', 'glargine', 'levemir', 'detemir', 'tresiba', 'degludec']):
                    # This suggests they're MDI users, not pump users - keep original basal
                    return basal
                else:
                    # True pump user - make basal match bolus
                    return bolus
            elif pd.notna(bolus) and pd.isna(basal):
                # Pump user with bolus but no basal - use bolus for basal
                return bolus
            elif pd.isna(bolus) and pd.notna(basal):
                # Pump user with basal but no bolus - use basal for bolus (handle in next step)
                return basal
        
        return basal
    
    user_data_expansion['insulin_type_basal'] = user_data_expansion.apply(fix_pump_insulin_types, axis=1)
    
    # Also fix bolus to match basal if needed for pump users
    def fix_bolus_matching(row):
        modality = row['insulin_delivery_modality']
        bolus = row['insulin_type_bolus']
        basal = row['insulin_type_basal']
        
        # For pump users (SAP/AID), bolus should equal basal
        if modality in ['SAP', 'AID']:
            if pd.isna(bolus) and pd.notna(basal):
                # If basal is not a long-acting insulin, use it for bolus too
                if not any(long_acting in str(basal).lower() for long_acting in ['lantus', 'glargine', 'levemir', 'detemir', 'tresiba', 'degludec']):
                    return basal
        
        return bolus
    
    user_data_expansion['insulin_type_bolus'] = user_data_expansion.apply(fix_bolus_matching, axis=1)
    
    # Final correction of delivery modality based on insulin types
    def correct_delivery_modality(row):
        device = row['insulin_delivery_device']
        algorithm = row['insulin_delivery_algorithm']
        basal = row['insulin_type_basal']
        
        # If device is t:slim X2 with Control-IQ, definitely AID (pump user)
        if device == 't:slim X2' and algorithm == 'Control-IQ':
            return 'AID'
        
        # If device is t:slim X2 with Basal-IQ, definitely SAP (pump user)
        if device == 't:slim X2' and algorithm == 'Basal-IQ':
            return 'SAP'
        
        # If device is OmniPod, definitely pump user
        if device == 'OmniPod':
            if algorithm == 'Control-IQ':
                return 'AID'
            else:
                return 'SAP'
        
        # If device is Medtronic with SmartGuard, definitely SAP (pump user)
        if 'Medtronic' in str(device) and algorithm == 'SmartGuard':
            return 'SAP'
        
        # For cases with no device/algorithm but long-acting basal insulin, likely MDI
        if (pd.isna(device) or device == '') and (pd.isna(algorithm) or algorithm == ''):
            if pd.notna(basal) and any(long_acting in str(basal).lower() for long_acting in ['lantus', 'glargine', 'levemir', 'detemir', 'tresiba', 'degludec']):
                if '1 time per day' in str(basal) or 'once daily' in str(basal).lower():
                    return 'MDI'
        
        return row['insulin_delivery_modality']
    
    user_data_expansion['insulin_delivery_modality'] = user_data_expansion.apply(correct_delivery_modality, axis=1)
    
    print(f"User data expansion created with {len(user_data_expansion)} participants")
    
    print("\nDistributions:")
    print(f"Treatment groups: {merged_data['TrtGroup'].value_counts().to_dict()}")
    print(f"Insulin delivery devices: {user_data_expansion['insulin_delivery_device'].value_counts(dropna=False).to_dict()}")
    print(f"Insulin delivery algorithms: {user_data_expansion['insulin_delivery_algorithm'].value_counts().to_dict()}")
    print(f"Insulin delivery modalities: {user_data_expansion['insulin_delivery_modality'].value_counts(dropna=False).to_dict()}")
    print(f"CGM devices: {user_data_expansion['cgm_device'].value_counts().to_dict()}")
    print(f"Ethnicity: {user_data_expansion['ethnicity'].value_counts().to_dict()}")
    print(f"Insulin type bolus: {user_data_expansion['insulin_type_bolus'].value_counts(dropna=False).to_dict()}")
    print(f"Insulin type basal: {user_data_expansion['insulin_type_basal'].value_counts(dropna=False).to_dict()}")
    
    return user_data_expansion

def update_pedap_data(df):
    """Apply standardizations to PEDAP data"""
    print("\n" + "=" * 50)
    print("APPLYING PEDAP DATA STANDARDIZATIONS")
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
        df['insulin_delivery_modality'] = df['insulin_delivery_modality'].fillna('SAP')
        print(f"✓ Filled {modality_nulls} null values in insulin_delivery_modality with 'SAP'")
    
    device_nulls = df['insulin_delivery_device'].isnull().sum()
    if device_nulls > 0:
        df['insulin_delivery_device'] = df['insulin_delivery_device'].fillna('t:slim X2')
        print(f"✓ Filled {device_nulls} null values in insulin_delivery_device with 't:slim X2'")
    
    print(f"\nStandardization complete for {len(df)} participants")
    return df

def main():
    """Main processing function"""
    output_path = "data/user_data_expansion/"
    
    # Step 1: Generate PEDAP data
    df = generate_pedap_data()
    
    # Step 2: Apply standardizations
    df = update_pedap_data(df)
    
    # Step 3: Save dataframe
    print("\nSaving dataframe...")
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, "PEDAP.csv")
    df.to_csv(output_file, index=False)
    
    print(f"✓ Saved PEDAP dataframe to: {output_file}")
    
    # Final summary
    print("\n" + "=" * 70)
    print("PEDAP DATA PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Total participants: {len(df)}")
    print(f"Total columns: {len(df.columns)}")
    print("Dataset ready for analysis!")
    
    return df

if __name__ == "__main__":
    df = main()