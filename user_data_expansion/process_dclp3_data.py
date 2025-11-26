#!/usr/bin/env python3
"""
Process DCLP3 data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os
import boto3
from io import StringIO
from helpers import prioritize_insulin_choice, get_pump_insulin_types_for_patient, process_s3_data

def generate_dclp3_data():
    """Generate DCLP3 user data expansion"""
    # Set up file paths
    dclp3_data_path = "data/raw/DCLP3 Public Dataset - Release 3 - 2022-08-04/Data Files/"
    output_path = "data/user_data_expansion/"
    
    print("DCLP3 User Data Expansion Pipeline")
    print("=" * 50)

    # Step 1: Read roster
    print("Step 1: Reading participant roster...")
    roster_file = os.path.join(dclp3_data_path, "PtRoster_a.txt")
    roster_df = pd.read_csv(roster_file, delimiter="|", encoding='utf-16')
    print(f"Roster shape: {roster_df.shape}")
    print(f"Columns: {roster_df.columns.tolist()}")
    
    # Step 2: Read insulin data
    print("\nStep 2: Reading insulin data...")
    insulin_file = os.path.join(dclp3_data_path, "Insulin_a.txt")
    insulin_df = pd.read_csv(insulin_file, delimiter="|", encoding='utf-16')
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

    print(final_df['trtGroup'].value_counts(dropna=False))
    final_df['insulin_delivery_algorithm'] = final_df['trtGroup'].map({
        'SAP': 'basal-bolus',
        'CLC': 'Control-IQ'
    })
    
    print(f"Treatment groups: {final_df['trtGroup'].value_counts().to_dict()}")
    print(f"Algorithms: {final_df['insulin_delivery_algorithm'].value_counts().to_dict()}")
    
    # Step 6: Add CGM device
    print("\nStep 6: Adding CGM device information...")
    final_df['cgm_device'] = "Dexcom G6"  # As stated in the protocol, all will use Dexcom G6
    
    # Step 7: Add ethnicity
    print("\nStep 7: Adding ethnicity information...")
    try:
        screening_file = os.path.join(dclp3_data_path, "DiabScreening_a.txt")
        screening_df = pd.read_csv(screening_file, delimiter="|", encoding='utf-16')
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
    final_df['is_pregnant'] = False  # Pregnancy was exclusion criterion
    
    # Step 10: Add delivery modality
    print("\nStep 10: Adding delivery modality...")
    final_df['insulin_delivery_modality'] = final_df['trtGroup'].map({
        'SAP': 'SAP',
        'CLC': 'AID'
    })
    
    # Step 11: Add insulin types (pump-only)
    print("\nStep 11: Adding insulin types...")
    pump_insulin_results = []
    for ptid in final_df['PtID']:
        bolus, basal = get_pump_insulin_types_for_patient(ptid, insulin_df, default='Humalog (Lispro) or Novolog (Aspart)')
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

def update_dclp3_data(df):
    """Apply standardizations to DCLP3 data"""
    print("\n" + "=" * 50)
    print("APPLYING DCLP3 DATA STANDARDIZATIONS")
    print("=" * 50)
    
    # Apply ethnicity value renaming
    ethnicity_mapping = {
        "Unknown/not reported, Hispanic/Latino": "Hispanic/Latino",
        "White/Native Hawaiian/Other Pacific Islander": "White, Native Hawaiian/Other Pacific Islander", 
        "Mexican, Hispanic/Latino": "Hispanic/Latino",
        "Vietnamese, Hispanic/Latino, German": "White, Asian, Hispanic/Latino"
    }
    
    print("Applying ethnicity mappings:")
    for old_value, new_value in ethnicity_mapping.items():
        count = (df['ethnicity'] == old_value).sum()
        if count > 0:
            df['ethnicity'] = df['ethnicity'].replace(old_value, new_value)
            print(f"  '{old_value}' → '{new_value}' ({count} records)")
    
    print(f"\nStandardization complete for {len(df)} participants")
    return df



def main():
    """Main processing function"""
    output_path = "data/user_data_expansion/"
    
    # Step 1: Generate DCLP3 data
    df = generate_dclp3_data()
    
    # Step 2: Apply standardizations
    df = update_dclp3_data(df)
    
    # Step 3: Save local dataframe
    print("\nSaving local dataframe...")
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, "DCLP3.csv")
    df.to_csv(output_file, index=False)
    print(f"✓ Saved DCLP3 dataframe to: {output_file}")

    df_resampled = pd.read_csv('data/resampled/DCLP3.csv')
    df_resampled['insulin'] = df_resampled['bolus'].fillna(0) + df_resampled['basal']

    # Step 4: Process S3 data if available
    print("\nAttempting S3 data processing...")
    s3_df = process_s3_data(df.copy(), 'DCLP3', df=df_resampled)
    if s3_df is not None:
        print("✓ S3 processing completed successfully")
    else:
        print("⚠ S3 processing failed, continuing with local data only")
    
    # Final summary
    print("\n" + "=" * 70)
    print("DCLP3 DATA PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Total participants: {len(df)}")
    print(f"Total columns: {len(df.columns)}")
    print("Dataset ready for analysis!")
    
    return df

if __name__ == "__main__":
    df = main()