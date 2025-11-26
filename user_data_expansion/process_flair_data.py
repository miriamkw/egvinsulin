#!/usr/bin/env python3
"""
Process FLAIR data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os
from helpers import get_pump_insulin_types_for_patient, process_s3_data

def generate_flair_data():
    """Generate FLAIR user data expansion following DCLP3/DCLP5 pattern"""
    # Set up file paths
    flair_data_path = "data/raw/FLAIRPublicDataSet/Data Tables/"
    output_path = "data/user_data_expansion/"
    
    print("FLAIR User Data Expansion Pipeline")
    print("=" * 50)
    
    # Step 1: Read roster
    print("Step 1: Reading participant roster...")
    roster_file = os.path.join(flair_data_path, "PtRoster.txt")
    roster_df = pd.read_csv(roster_file, delimiter="|")
    print(f"Roster shape: {roster_df.shape}")
    print(f"Columns: {roster_df.columns.tolist()}")
    print(f"Treatment groups: {roster_df['TrtGroup'].value_counts().to_dict()}")
    
    # Step 2: Read insulin data 
    print("\nStep 2: Reading insulin data...")
    insulin_file = os.path.join(flair_data_path, "FLAIRInsulin.txt")
    insulin_df = pd.read_csv(insulin_file, delimiter="|")
    print(f"Insulin data shape: {insulin_df.shape}")

    # Step 4: Create base dataframe
    print("\nStep 4: Creating base dataframe...")
    final_df = roster_df[['PtID', 'SiteID', 'EnrollDt', 'RandDt', 'PtStatus', 'TrtGroup', 'AgeAsofEnrollDt', 'RandDt']].copy()

    # FLAIR used MiniMed 670G system
    final_df['insulin_delivery_device'] = 'MiniMed 670G'  # Based on protocol
    
    # Step 5: Update device specifics for FLAIR (MiniMed 670G system)
    print("\nStep 5: Updating device specifics...")

    # Map treatment groups to algorithms
    final_df['insulin_delivery_algorithm'] = final_df['TrtGroup'].map({
        '670G': 'SmartGuard',  # SmartGuard HCL
        'AHCL': '780G Advanced HCL'    # Advanced Hybrid Closed Loop
    })
    
    # Map treatment groups to modalities, all used AID in this study
    final_df['insulin_delivery_modality'] = 'AID'
    
    print(f"Treatment groups: {final_df['TrtGroup'].value_counts().to_dict()}")
    print(f"Algorithms: {final_df['insulin_delivery_algorithm'].value_counts().to_dict()}")
    print(f"Modalities: {final_df['insulin_delivery_modality'].value_counts().to_dict()}")
    
    # Step 6: Add CGM device (Guardian 3 for MiniMed 670G system)
    print("\nStep 6: Adding CGM device information...")
    final_df['cgm_device'] = "Guardian 3"  # FLAIR used Guardian 3 with MiniMed 670G
    print(f"CGM device distribution: {final_df['cgm_device'].value_counts(dropna=False).to_dict()}")

    # Step 7: Add ethnicity
    print("\nStep 7: Adding ethnicity information...")
    try:
        screening_file = os.path.join(flair_data_path, "FLAIRDiabScreening.txt")
        screening_df = pd.read_csv(screening_file, delimiter="|")
        ethnicity_data = screening_df[['PtID', 'Ethnicity', 'Race']].copy()
        
        def format_ethnicity(row):
            race = row['Race']
            ethnicity = row['Ethnicity'] 
            
            if pd.isna(race) or race == '':
                return np.nan
            
            # Start with race
            formatted_race = race
            
            # Add Hispanic/Latino if applicable
            if pd.notna(ethnicity) and ethnicity == 'Hispanic or Latino':
                if 'Hispanic/Latino' not in formatted_race:
                    formatted_race += ', Hispanic/Latino'
            
            return formatted_race
        
        ethnicity_data['formatted_ethnicity'] = ethnicity_data.apply(format_ethnicity, axis=1)
        ethnicity_mapping = ethnicity_data[['PtID', 'formatted_ethnicity']].copy()
        ethnicity_mapping.columns = ['PtID', 'ethnicity']
        
        final_df = final_df.merge(ethnicity_mapping, on='PtID', how='left')
        
        print(f"Ethnicity categories: {len(final_df['ethnicity'].unique())} unique values")
        print(f"Ethnicity distribution: {final_df['ethnicity'].value_counts(dropna=False).to_dict()}")

        # Add gender
        final_df = final_df.merge(screening_df[['PtID', 'Sex']], on='PtID', how='left')
        final_df.rename(columns={'Sex': 'gender'}, inplace=True)
        final_df['gender'] = final_df['gender'].map({'M': 'Male', 'F': 'Female'})

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
    # Pregnancy is exclusion criterion, and all tests in FLAIRDiabPregnancyTest.txt are negative
    final_df['is_pregnant'] = False
    print("Set is_pregnant = False for all participants (clinical trial exclusion)")

    # Step 10: Add insulin types (pump-only) using improved helper function
    print("\nStep 10: Adding insulin types...")
    
    pump_insulin_results = []
    for ptid in final_df['PtID']:
        bolus, basal = get_pump_insulin_types_for_patient(ptid, insulin_df, insulin_name_column='InsulinName', default='Humalog (Lispro) or Novolog (Aspart)')
        pump_insulin_results.append({
            'PtID': ptid,
            'insulin_type_bolus': bolus,
            'insulin_type_basal': basal
        })
    
    pump_insulin_df = pd.DataFrame(pump_insulin_results)
    final_df = final_df.merge(pump_insulin_df, on='PtID', how='left')
    
    # For pump patients, use same insulin for bolus and basal if basal is missing
    final_df.loc[
        (final_df['insulin_delivery_device'] == 'MiniMed 670G') & 
        (final_df['insulin_type_basal'].isna()) & 
        (final_df['insulin_type_bolus'].notna()),
        'insulin_type_basal'
    ] = final_df.loc[
        (final_df['insulin_delivery_device'] == 'MiniMed 670G') & 
        (final_df['insulin_type_basal'].isna()) & 
        (final_df['insulin_type_bolus'].notna()),
        'insulin_type_bolus'
    ]
    
    print(f"Bolus insulin types: {final_df['insulin_type_bolus'].value_counts(dropna=False).to_dict()}")
    print(f"Basal insulin types: {final_df['insulin_type_basal'].value_counts(dropna=False).to_dict()}")
    
    # Step 11: Final cleanup
    print("\nStep 11: Final cleanup...")
    final_df = final_df.rename(columns={'PtID': 'id', 'TrtGroup': 'treatment_group', 'RandDt': 'randomization_date'})
    columns_to_drop = ['SiteID', 'EnrollDt', 'PtStatus', 'AgeAsofEnrollDt']
    final_df = final_df.drop(columns=columns_to_drop)
    
    print(f"Final shape: {final_df.shape}")
    print(f"Final columns: {final_df.columns.tolist()}")
    
    return final_df

def update_flair_data(df):
    """Apply standardizations to FLAIR data"""
    print("\n" + "=" * 50)
    print("APPLYING FLAIR DATA STANDARDIZATIONS")
    print("=" * 50)
    
    # Show current null counts
    print("\nCurrent null value counts:")
    null_counts = df.isnull().sum()
    for col, count in null_counts.items():
        if count > 0:
            print(f"  {col}: {count} null values")
    
    # Show current distributions
    print("\nCurrent distributions:")
    print("Treatment assignments:")
    print("insulin_delivery_algorithm:")
    algorithm_dist = df['insulin_delivery_algorithm'].value_counts(dropna=False)
    for value, count in algorithm_dist.items():
        print(f"  {value}: {count}")
    
    print("insulin_delivery_modality:")
    modality_dist = df['insulin_delivery_modality'].value_counts(dropna=False)
    for value, count in modality_dist.items():
        print(f"  {value}: {count}")
        
    print("insulin_delivery_device:")
    device_dist = df['insulin_delivery_device'].value_counts(dropna=False)
    for value, count in device_dist.items():
        print(f"  {value}: {count}")

    # 3. Fill null values in insulin_delivery_device with "MiniMed 670G"
    print("\n3. Filling null values in insulin_delivery_device...")
    device_nulls = df['insulin_delivery_device'].isnull().sum()
    if device_nulls > 0:
        print(f"   Found {device_nulls} null values")
        df['insulin_delivery_device'] = df['insulin_delivery_device'].fillna('MiniMed 670G')
        print(f"   ✓ Filled with 'MiniMed 670G'")
    else:
        print("   ✓ No null values found")
    
    # 4. Standardize ethnicity categories
    print("\n4. Standardizing ethnicity categories...")
    print("   Current ethnicity distribution:")
    current_ethnicities = df['ethnicity'].value_counts(dropna=False)
    for ethnicity, count in current_ethnicities.items():
        print(f"     {ethnicity}: {count}")
    
    # Define ethnicity mappings (more conservative than DCLP5 since FLAIR has fewer mixed categories)
    ethnicity_mappings = {
        # Add any specific mappings found in FLAIR data if needed
    }
    
    if ethnicity_mappings:
        print(f"\n   Applying ethnicity mappings:")
        for old_value, new_value in ethnicity_mappings.items():
            count = (df['ethnicity'] == old_value).sum()
            if count > 0:
                df['ethnicity'] = df['ethnicity'].replace(old_value, new_value)
                print(f"     '{old_value}' → '{new_value}' ({count} records)")
    else:
        print("   ✓ No ethnicity mappings needed - categories already standardized")
    
    # Final verification - check for any remaining null values in key columns
    print("\n5. Final verification...")
    final_null_counts = df.isnull().sum()
    key_columns = ['insulin_delivery_algorithm', 'insulin_delivery_modality', 'insulin_delivery_device']
    remaining_nulls = final_null_counts[key_columns]
    remaining_nulls = remaining_nulls[remaining_nulls > 0]
    
    if len(remaining_nulls) > 0:
        print("   Remaining null values in key columns:")
        for col, count in remaining_nulls.items():
            print(f"     {col}: {count} null values")
    else:
        print("   ✓ No remaining null values in key columns")
    
    # Show final distributions
    print("\n   Final distributions:")
    print("   insulin_delivery_algorithm:")
    for value, count in df['insulin_delivery_algorithm'].value_counts().items():
        print(f"     {value}: {count}")
    
    print("   insulin_delivery_modality:")
    for value, count in df['insulin_delivery_modality'].value_counts().items():
        print(f"     {value}: {count}")
        
    print("   insulin_delivery_device:")
    for value, count in df['insulin_delivery_device'].value_counts().items():
        print(f"     {value}: {count}")
    
    print(f"\nSTANDARDIZATION SUMMARY:")
    if device_nulls > 0:
        print(f"✓ Updated {device_nulls} records: insulin_delivery_device null → 'MiniMed 670G'")
    print(f"✓ Final shape: {df.shape}")
    
    return df

def main():
    """Main processing function"""
    output_path = "data/user_data_expansion/"
    
    # Step 1: Generate FLAIR data
    df = generate_flair_data()
    
    # Step 2: Apply standardizations
    df = update_flair_data(df)
    
    # Step 3: Save final dataframe
    print("\nSaving final dataframe...")
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, "Flair.csv")
    df.to_csv(output_file, index=False)
    
    print(f"✓ Saved FLAIR dataframe to: {output_file}")

    resampled_df = pd.read_csv(f'data/resampled/Flair.csv')
    resampled_df['basal'] = resampled_df['basal'] / 12  # From U/hr to U
    resampled_df['insulin'] = resampled_df['bolus'].fillna(0) + resampled_df['basal']
    resampled_df['gender'] = resampled_df['gender'].map({'F': 'Female', 'M': 'Male'})
    resampled_df['source_file'] = 'Flair'
    
    # Step 4: Process S3 data if available
    print("\nAttempting S3 data processing...")
    s3_df = process_s3_data(df.copy(), 'Flair', df=resampled_df)
    if s3_df is not None:
        print("✓ S3 processing completed successfully")
    else:
        print("⚠ S3 processing failed, continuing with local data only")
    
    # Final summary
    print("\n" + "=" * 70)
    print("FLAIR DATA PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Total participants: {len(df)}")
    print(f"Total columns: {len(df.columns)}")
    print("Dataset ready for analysis!")
    
    # Show final distributions
    print("\nFinal distributions:")
    print("insulin_delivery_algorithm:")
    for value, count in df['insulin_delivery_algorithm'].value_counts(dropna=False).items():
        print(f"  {value}: {count}")
    
    print("insulin_delivery_modality:")
    for value, count in df['insulin_delivery_modality'].value_counts(dropna=False).items():
        print(f"  {value}: {count}")
    
    print("cgm_device:")
    for value, count in df['cgm_device'].value_counts(dropna=False).items():
        print(f"  {value}: {count}")
    
    return df

if __name__ == "__main__":
    df = main()