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



