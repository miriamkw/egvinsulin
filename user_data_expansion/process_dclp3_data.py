#!/usr/bin/env python3
"""
Process DCLP3 data: Generate user data expansion and apply standardizations
"""

import pandas as pd
import numpy as np
import os
import boto3
from io import StringIO

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
        # Filter to only pump insulin records
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


def process_s3_data(df_expansion_data_copy):
    """Process DCLP3 data with S3 integration"""
    print("\n" + "=" * 50)
    print("S3 DATA PROCESSING PIPELINE")
    print("=" * 50)
    
    bucket_name = 'replica-general-data-repository'
    file_name = 'DCLP3.csv'
    
    try:
        # Step 1: Load from S3
        print("Step 1: Loading data from S3...")
        obj_key = f'processed_data_final_expanded/{file_name}'
        s3 = boto3.client("s3")
        obj_response = s3.get_object(Bucket=bucket_name, Key=obj_key)
        content = obj_response["Body"].read().decode("utf-8")
        df = pd.read_csv(StringIO(content))
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


        # Step 4: Convert weight/height units
        print("\nStep 4: Converting weight and height units...")
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

        # Step 5: Save the updated df locally
        print("\nStep 5: Saving updated dataframe locally...")
        output_file = "DCLP3_s3_merged.csv"
        df.to_csv(output_file, index=False)
        print(f"✓ Saved merged S3 dataframe to: {output_file}")
        print(f"  Final merged dataset shape: {df.shape}")

        # Step 6: Analyze updated dataframe with value counts (including NaNs)
        print("\nStep 6: Analyzing merged dataframe...")
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
    
    # Step 4: Process S3 data if available
    print("\nAttempting S3 data processing...")
    process_s3_data(df.copy())
    
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