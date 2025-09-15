#!/usr/bin/env python3
"""
Process DCLP5 data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os

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
    
    # Step 3: Determine primary delivery device
    print("\nStep 3: Determining primary insulin delivery device...")
    def get_primary_insulin_delivery(patient_data):
        if 'Pump' in patient_data['InsRoute'].values:
            return 'Pump'
        else:
            return 'Injection'
    
    patient_delivery = insulin_df.groupby('PtID').apply(get_primary_insulin_delivery)
    patient_delivery_df = patient_delivery.reset_index()
    patient_delivery_df.columns = ['PtID', 'insulin_delivery_device']
    
    print(f"Delivery device distribution: {patient_delivery_df['insulin_delivery_device'].value_counts().to_dict()}")
    
    # Step 4: Create base dataframe
    print("\nStep 4: Creating base dataframe...")
    final_df = roster_df[['PtID', 'EnrollDt', 'RandDt', 'trtGroup', 'PtStatus', 'SiteID']].copy()
    final_df = final_df.merge(patient_delivery_df, on='PtID', how='left')
    final_df['insulin_delivery_device'] = final_df['insulin_delivery_device'].fillna('Unknown')
    
    # Step 5: Update device specifics
    print("\nStep 5: Updating device specifics...")
    final_df['insulin_delivery_device'] = final_df['insulin_delivery_device'].replace('Pump', 't:slim X2')
    final_df['insulin_delivery_algorithm'] = final_df['trtGroup'].map({
        'SAP': 'basal-bolus',
        'CLC': 'Control-IQ'
    })
    
    print(f"Treatment groups: {final_df['trtGroup'].value_counts().to_dict()}")
    print(f"Algorithms: {final_df['insulin_delivery_algorithm'].value_counts().to_dict()}")
    
    # Step 6: Add CGM device
    print("\nStep 6: Adding CGM device information...")
    try:
        dexcom_clarity_file = os.path.join(dclp5_data_path, "DexcomClarityCGM.txt")
        dexcom_clarity_df = pd.read_csv(dexcom_clarity_file, delimiter="|")
        dexcom_ptids = set(dexcom_clarity_df['PtID'].unique())
        
        other_cgm_file = os.path.join(dclp5_data_path, "OtherCGM.txt")  
        other_cgm_df = pd.read_csv(other_cgm_file, delimiter="|")
        other_cgm_ptids = set(other_cgm_df['PtID'].unique())
        
        all_cgm_ptids = dexcom_ptids.union(other_cgm_ptids)
        
        def assign_cgm_device(ptid):
            if ptid in all_cgm_ptids:
                return "Dexcom G6"  # DCLP5 used G6 (2019-2021 era)
            else:
                return np.nan
        
        final_df['cgm_device'] = final_df['PtID'].apply(assign_cgm_device)
        
        print(f"CGM coverage: {len(all_cgm_ptids)} out of {len(final_df)} participants")
        print(f"CGM device distribution: {final_df['cgm_device'].value_counts(dropna=False).to_dict()}")
        
    except Exception as e:
        print(f"Error reading CGM data: {e}")
        final_df['cgm_device'] = "Dexcom G6"  # Default for DCLP5 era
    
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
        
    except Exception as e:
        print(f"Error reading ethnicity data: {e}")
        final_df['ethnicity'] = np.nan
    
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
        'SAP': 'SAP',
        'CLC': 'AID'
    })
    
    # Step 11: Add insulin types (pump-only)
    print("\nStep 11: Adding insulin types...")
    bolus_insulins = [
        'Novolog (Aspart)', 'Humalog (Lispro)', 'Novolog Fiasp',
        'Regular (R) (Humulin R or Novolin R)', 'Admelog'
    ]
    
    basal_insulins = [
        'Lantus (Glargine) 2 times per day', 'Lantus (Glargine) 1 time per day', 
        'Degludec (Tresiba)', 'Toujeo (Glargine, U300)', 
        'Basaglar (Glargine, U100)', 'Levemir (Detemir) 1 time per day'
    ]
    
    def get_pump_insulin_types_for_patient(ptid, insulin_data):
        patient_pump_insulin = insulin_data[(insulin_data['PtID'] == ptid) & (insulin_data['InsRoute'] == 'Pump')]
        
        bolus_insulins_found = []
        basal_insulins_found = []
        
        for _, row in patient_pump_insulin.iterrows():
            insulin_name = row['ParentInsulinListID']
            if pd.notna(insulin_name):
                if insulin_name in bolus_insulins:
                    bolus_insulins_found.append(insulin_name)
                elif insulin_name in basal_insulins:
                    basal_insulins_found.append(insulin_name)
        
        bolus_unique = list(set(bolus_insulins_found))
        basal_unique = list(set(basal_insulins_found))
        
        bolus_result = '; '.join(bolus_unique) if bolus_unique else np.nan
        basal_result = '; '.join(basal_unique) if basal_unique else np.nan
        
        return bolus_result, basal_result
    
    pump_insulin_results = []
    for ptid in final_df['PtID']:
        bolus, basal = get_pump_insulin_types_for_patient(ptid, insulin_df)
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
    final_df = final_df.rename(columns={'PtID': 'id'})
    columns_to_drop = ['EnrollDt', 'RandDt', 'trtGroup', 'PtStatus', 'SiteID']
    final_df = final_df.drop(columns=columns_to_drop)
    
    print(f"Final shape: {final_df.shape}")
    print(f"Final columns: {final_df.columns.tolist()}")
    
    return final_df

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
    
    # 1. Fill null values in insulin_delivery_algorithm with "basal-bolus"
    print("\n1. Filling null values in insulin_delivery_algorithm...")
    algorithm_nulls = df['insulin_delivery_algorithm'].isnull().sum()
    print(f"   Found {algorithm_nulls} null values")
    df['insulin_delivery_algorithm'] = df['insulin_delivery_algorithm'].fillna('basal-bolus')
    print(f"   ✓ Filled with 'basal-bolus'")
    
    # 2. Fill null values in insulin_delivery_modality with "SAP"
    print("\n2. Filling null values in insulin_delivery_modality...")
    modality_nulls = df['insulin_delivery_modality'].isnull().sum()
    print(f"   Found {modality_nulls} null values")
    df['insulin_delivery_modality'] = df['insulin_delivery_modality'].fillna('SAP')
    print(f"   ✓ Filled with 'SAP'")
    
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
    print(f"✓ Updated {algorithm_nulls} records: insulin_delivery_algorithm null → 'basal-bolus'")
    print(f"✓ Updated {modality_nulls} records: insulin_delivery_modality null → 'SAP'")
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