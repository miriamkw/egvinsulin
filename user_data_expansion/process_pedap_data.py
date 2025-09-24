#!/usr/bin/env python3
"""
Process PEDAP data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os
from helpers import prioritize_insulin_choice, process_s3_data

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
    
    # Step 2: Load screening data for demographic information
    print("\nStep 2: Reading screening data...")
    screening = pd.read_csv(os.path.join(base_path, 'PEDAPDiabScreening.txt'), delimiter='|')
    print(f"Screening shape: {screening.shape}")
    
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
    
    # All PEDAP participants use the same setup (pediatric AID study)
    user_data_expansion['insulin_delivery_device'] = 't:slim X2'
    user_data_expansion['insulin_delivery_algorithm'] = 'Control-IQ'
    user_data_expansion['cgm_device'] = 'Dexcom G6'
    user_data_expansion['insulin_delivery_modality'] = 'AID'
    
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
    
    # Step 6: Load insulin data for insulin types
    print("\nStep 6: Processing insulin types...")
    insulin_data = pd.read_csv(os.path.join(base_path, 'PEDAPInsulin.txt'), delimiter='|')
    print(f"Insulin data shape: {insulin_data.shape}")
    print("Insulin type start distribution:")
    print(insulin_data['InsTypeStart'].value_counts().to_dict())
    
    def get_pedap_insulin_types_for_patient(ptid, insulin_data):
        """
        PEDAP-specific insulin type detection that handles both pump and MDI users.
        Uses improved prioritization logic while respecting PEDAP's enrollment timing priorities.
        """
        try:
            # Get all insulin records for this patient
            patient_insulin = insulin_data[insulin_data['PtID'] == ptid].copy()
            
            if patient_insulin.empty:
                print(f"No insulin data found for patient {ptid}")
                return np.nan, np.nan

            # Search for Aspart and Lispro in all records (PEDAP's main fast-acting insulins)
            aspart_rows = patient_insulin[
                patient_insulin['InsulinName'].str.contains(
                    'Aspart|Novolog', case=False, na=False
                )
            ]
            lispro_rows = patient_insulin[
                patient_insulin['InsulinName'].str.contains(
                    'Lispro|Humalog', case=False, na=False  
                )
            ]
            
            has_aspart = not aspart_rows.empty
            has_lispro = not lispro_rows.empty
            
            # Log available options
            available_options = []
            if has_aspart:
                available_options.append("Aspart/Novolog")
            if has_lispro:
                available_options.append("Lispro/Humalog")
            
            if len(available_options) > 1:
                print(f"Patient {ptid}: Has multiple insulin options: {', '.join(available_options)}")
            
            chosen_insulin = None
            
            # Determine which insulin to use with PEDAP-specific prioritization
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

            print(f"Patient {ptid}: Assigned insulin type '{chosen_insulin}' for both bolus and basal")
            
            # Return the same insulin for both bolus and basal (pump patients use same insulin)
            return chosen_insulin, chosen_insulin
            
        except Exception as e:
            print(f"Error processing insulin data for patient {ptid}: {e}")
            return np.nan, np.nan
    
    # Apply the improved insulin mapping
    insulin_results = []
    for ptid in merged_data['PtID']:
        bolus, basal = get_pedap_insulin_types_for_patient(ptid, insulin_data)
        insulin_results.append({
            'PtID': ptid,
            'insulin_type_bolus': bolus,
            'insulin_type_basal': basal
        })
    
    insulin_df = pd.DataFrame(insulin_results)
    user_data_expansion = user_data_expansion.merge(insulin_df, left_on='id', right_on='PtID', how='left')
    user_data_expansion = user_data_expansion.drop(columns=['PtID'])
    
    # Step 7: Insulin types are now handled by the improved function
    print("\nStep 7: Insulin types processed with improved detection logic...")
    
    
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
    
    # Verify all participants have consistent device/algorithm/modality (should be no nulls)
    algorithm_nulls = df['insulin_delivery_algorithm'].isnull().sum()
    modality_nulls = df['insulin_delivery_modality'].isnull().sum()
    device_nulls = df['insulin_delivery_device'].isnull().sum()
    
    if algorithm_nulls > 0 or modality_nulls > 0 or device_nulls > 0:
        print(f"⚠ Warning: Found unexpected null values:")
        if algorithm_nulls > 0:
            print(f"  insulin_delivery_algorithm: {algorithm_nulls} nulls")
        if modality_nulls > 0:
            print(f"  insulin_delivery_modality: {modality_nulls} nulls")
        if device_nulls > 0:
            print(f"  insulin_delivery_device: {device_nulls} nulls")
    else:
        print("✓ All participants have consistent device/algorithm/modality assignments")
    
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
    
    # Step 4: Process S3 data if available
    print("\nAttempting S3 data processing...")
    s3_df = process_s3_data(df.copy(), 'PEDAP')
    if s3_df is not None:
        print("✓ S3 processing completed successfully")
    else:
        print("⚠ S3 processing failed, continuing with local data only")
    
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