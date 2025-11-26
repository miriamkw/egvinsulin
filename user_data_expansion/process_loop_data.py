import pandas as pd
import numpy as np
import os
from helpers import process_s3_data


raw_data_file_path = "data/raw/Loop study public dataset 2023-01-31/Data Tables/"


def get_df_from_file(file_path, file_name, parse_datetime=True, sep=',', encoding='utf-8'):
    df = pd.read_csv(file_path + file_name, sep=sep, on_bad_lines='skip', encoding=encoding)
    if parse_datetime:
        df['date'] = pd.to_datetime(df['datetime'], unit='s')
    return df


def get_loop_expansion_data():

    # Add gender
    df_user_data = get_df_from_file(raw_data_file_path, 'Surveys.txt', parse_datetime=False, sep='|')

    relevant_columns = ['SubjectID', 'gender', 'weight', 'height_feet', 'height_inches', 'age_diabetes_developed',
                        'insulin_type', 'pump_type_use', 'what_cgm', 'pregnant', 'race', 'ethnicity', 'race_multiple']
    df_user_data = df_user_data[relevant_columns]
    df_user_data = df_user_data.dropna(how='all', subset=['gender', 'weight', 'height_feet', 'height_inches'])
    # Weight is already in Ibs
    # Height in feet
    df_user_data['height'] = df_user_data.apply(
        lambda row: row['height_feet'] + (row['height_inches'] / 12),
        axis=1
    )
    # Gender from int to string
    df_user_data['gender'] = df_user_data['gender'].map({1: 'Male', 2: 'Female', 3: 'Non-binary'})

    df_user_data['insulin_type'] = df_user_data['insulin_type'].map({
        1: 'Humalog (Lispro)',
        2: 'Novolog (Aspart)',
        3: 'Apidra (Glusine)',
        4: 'Fiasp (Rapid Aspart)',
        5: 'Regular insulin'
    })

    df_user_data['pump_type_use'] = df_user_data['pump_type_use'].map({
        1: 'MiniMed 515/715',
        2: 'MiniMed 522/722',
        3: 'MiniMed 523/723',
        4: 'MiniMed 554/754',
        5: 'OmniPod'
    })

    df_user_data['what_cgm'] = df_user_data['what_cgm'].map({
        1: 'Dexcom G4',
        2: 'Dexcom G5',
        3: 'Dexcom G6',
        4: 'Medtronic Enlite',
        5: 'Abbott Libre'
    })

    df_user_data['pregnant'] = df_user_data['pregnant'].map({
        1: True,
        2: False,
        3: np.nan,
    })

    df_user_data['race'] = df_user_data['race'].map({
        1: 'White',
        2: 'Black/African-American',
        3: 'Asian',
        4: 'Native Hawaiian/Other Pacific Islander',
        5: 'American Indian/Alaskan Native',
        6: np.nan,
        7: '',
    })
    df_user_data['ethnicity'] = df_user_data['ethnicity'].map({
        1: ', Hispanic/Latino',
        2: '',
        3: ''
    })

    race_map = {
        'White, Asian': 'White, Asian',
        'White and Asian': 'White, Asian',
        'anglo, latino': 'White, Hispanic/Latino',
        'White Asian': 'White, Asian',
        'Asian, White': 'White, Asian',
        'Mexican, Colombian, Black, caucasian': 'White, Black/African-American, Hispanic/Latino',
        'Black, White, American Indian': 'White, Black/African-American, American Indian/Alaskan Native',
        'White, Puerto Rican, Black': 'White, Black/African-American, Hispanic/Latino',
        'Brazilian American': 'Hispanic/Latino',
        'caucasion & vietnamese': 'White, Asian',
        'South Asian mother and German father': 'White, Asian',
        'White, Native American, Hispanic': 'White, American Indian/Alaskan Native',  # Hispanic is given in the other
        'American Indian, White': 'White, American Indian/Alaskan Native',
        'White/Black': 'White, Black/African-American',
        'Lebanese and European': 'White',
        'White, African-American': 'White, Black/African-American',
        'Asian and Hispanic': 'Asian, Hispanic/Latino'
    }
    df_user_data['race_multiple_standard'] = df_user_data['race_multiple'].map(race_map)
    df_user_data['ethnicity_concat'] = df_user_data['race'].fillna('') + df_user_data['race_multiple_standard'].fillna('') + df_user_data['ethnicity']
    df_user_data['ethnicity_concat'].replace('', np.nan, inplace=True)
    df_user_data['ethnicity_concat'].replace(', Hispanic/Latino', 'Hispanic/Latino', inplace=True)

    df_user_data = df_user_data.rename(
        columns={'SubjectID': 'id', 'age_diabetes_developed': 'age_of_diagnosis', 'insulin_type': 'insulin_type_bolus',
                 'pump_type_use': 'insulin_delivery_device', 'what_cgm': 'cgm_device', 'pregnant': 'is_pregnant'})
    df_user_data['insulin_type_basal'] = df_user_data['insulin_type_bolus']

    df_user_data = df_user_data[
        ['id', 'gender', 'weight', 'height', 'age_of_diagnosis', 'insulin_type_bolus', 'insulin_type_basal',
         'insulin_delivery_device', 'cgm_device', 'ethnicity_concat', 'is_pregnant']]
    df_user_data.rename(columns={'ethnicity_concat': 'ethnicity'}, inplace=True)

    for col in df_user_data.drop(columns=['id', 'weight', 'height', 'age_of_diagnosis']).columns:
        print(f"{col} unique values: {df_user_data[col].value_counts(dropna=False)}")
    return df_user_data


def main():
    """Main processing function"""
    output_path = "data/user_data_expansion/"

    df = get_loop_expansion_data()

    # Step 3: Save dataframe
    print("\nSaving dataframe...")
    os.makedirs(output_path, exist_ok=True)
    output_file = os.path.join(output_path, "Loop.csv")
    df.to_csv(output_file, index=False)

    print(f"✓ Saved Loop expansion dataframe to: {output_file}")

    # Step 4: Process S3 data if available
    print("\nAttempting S3 data processing...")

    for i in range(8):
        name = f'Loop_Part{i+1}_of_8'

        resampled_df = pd.read_csv(f'data/resampled/{name}.csv')
        resampled_df['basal'] = resampled_df['basal'] / 12  # From U/hr to U
        resampled_df['insulin'] = resampled_df['bolus'].fillna(0) + resampled_df['basal']
        resampled_df['source_file'] = 'Loop'
        resampled_df['insulin_delivery_algorithm'] = 'LoopAlgorithm'
        resampled_df['insulin_delivery_modality'] = 'AID'

        for col in df.columns:
            if col not in resampled_df.columns:
                resampled_df[col] = np.nan

        s3_df = process_s3_data(df.copy(), name, df=resampled_df)

        # Final summary
        print("\n" + "=" * 70)
        print(f"LOOP {i+1}/8 DATA PROCESSING COMPLETE")
        print("=" * 70)
        print(f"Total participants: {len(s3_df)}")
        print(f"Total columns: {len(s3_df.columns)}")
        print("Dataset ready for analysis!")

    print("✓ S3 processing completed successfully")


if __name__ == "__main__":
    df = main()
