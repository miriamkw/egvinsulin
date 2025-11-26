# DCLP5

Sample Size
First phase: Up to 150 screened participants with the goal of randomizing 100 participants in this 16-week randomized trial.
Extension phase will consist of a partial crossover: All randomized participants will participate in an extension phase for another 12 weeks (total 28 weeks). The SC group (control group) will crossover to use Tandem t:slim X2 with Control-IQ for 12 weeks. The experimental arm will continue on the Control-IQ for 12 weeks.

16 weeks = 112 days
12 weeks = 84 days
16 + 12 = 28 weeks = 196 days

## Study Phase Date Information

### File Locations for Phase Dates and Participation

**Primary timeline data: `data/raw/DCLP5_Dataset_2022-01-20-5e0f3b16-c890-4ace-9e3b-531f3687cf53/PtRoster.txt`**
- `RandDt`: Exact start date of the 16-week randomized trial for each PtID
- `Phase2StartDt`: Exact start date of the 12-week extension phase for each PtID
- Note: Each patient has individual start dates rather than study-wide dates

**Extension phase participation: `data/raw/DCLP5_Dataset_2022-01-20-5e0f3b16-c890-4ace-9e3b-531f3687cf53/16WkCTV.txt`**
- `ExtPhaseCont`: Indicates whether each PtID continued into the extension phase (Yes/No)

### Key Findings
- The SC patients that are included in the extension phase will at one point transition from Basal-IQ / SAP to Control-IQ / AID. We will use the Phase2StartDt to determine that date. 



# PEDAP

Processing notes: 
- We found 7 carb values above 500g, out of a total of 102639 non-zero carb values. These values were set to nan.  


## CGM Data Quality Indicators

Values below and above 40 and 400 are set to 0 in the dataset, which Peter from JAEB made us aware of. In the dataset, there is a High/Low indicator, flagging the value to either below 40 or above 400. We analyzed the values before and after the High/Low value as a sanity check, and found the following:
```
ANALYZING INDICATOR HIGH
Min CGM value before 41.0
Median CGM value before 390.0
Mean CGM value before 324.0652713728272
Max CGM value before 400.0
Min CGM value after 49.0
Median CGM value after 389.0
Mean CGM value after 320.9964576691463
Max CGM value after 400.0

ANALYZING INDICATOR LOW
Min CGM value before 40.0
Median CGM value before 47.0
Mean CGM value before 61.64640410958904
Max CGM value before 389.0
Min CGM value after 40.0
Median CGM value after 48.0
Mean CGM value after 66.59519725557462
Max CGM value after 374.0
Remaining 0 values: 0
```
As we observe, it seems like some high / low value indicators have been mixed up or with high levels of noise. Hence, we set these values to nan. There are in total 31541 values that are changed from 0 to nan, out of a total of 5 026 538 CGM values in the dataset. 


# Loop

Processing notes: 
- The raw carbohydrate values in "LOOPDeviceFood.txt" have several duplicates where the carbohydrate and date value is identical. If we do not delete them, and sum them within 5-minute intervals, the meal size within a 5-minute interval becomes up to 102120g of carbs, which is not plausible as a meal size in one sitting. Hence, we delete all duplicate values where the value and date are identical. 
- We found 20 insulin doses above 50 units of insulin in Loop (and all subjects are AID, which makes large doses more unlikely than with MDI), out of 61701003 non-zero insulin values in the dataset. These doses are set to nan, and the following eight hours of data are also set to nan. 


