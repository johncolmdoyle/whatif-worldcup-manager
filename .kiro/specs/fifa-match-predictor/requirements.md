# Requirements Document

## Introduction

The FIFA Match Predictor is an application that ingests official FIFA World Cup match report PDFs, extracts structured match data (squads, events, statistics), and enables users to modify the starting lineup of either team. A prediction engine then simulates how the match outcome might have differed under the altered squad configuration, presenting the predicted result to the user.

## Glossary

- **Match_Report**: An official FIFA World Cup post-match PDF document containing lineups, substitutions, match events, and statistics.
- **PDF_Parser**: The system component responsible for reading and extracting structured data from Match_Report PDF files.
- **Match_Data**: The structured representation of information extracted from a Match_Report, including squads, events, and statistics.
- **Squad**: The full list of players (starting eleven plus substitutes) fielded by a team in a match.
- **Starting_Lineup**: The eleven players designated to begin the match on the pitch for a given team.
- **Player**: An individual footballer identified by name, position, and squad number as recorded in the Match_Report.
- **Match_Event**: A discrete occurrence during a match recorded in the Match_Report, including goals, yellow cards, red cards, and substitutions.
- **Match_Statistics**: Aggregated numerical data from a match, such as possession percentage, shots on target, passes, and fouls.
- **Lineup_Editor**: The UI component that allows the user to modify the Starting_Lineup by swapping players in or out.
- **Prediction_Engine**: The system component that simulates a match outcome based on the modified squad and extracted Match_Data.
- **Predicted_Outcome**: The simulated match result produced by the Prediction_Engine, including a predicted scoreline and key contributing factors.
- **System**: The FIFA Match Predictor application as a whole.

---

## Requirements

### Requirement 1: PDF Upload and Ingestion

**User Story:** As a user, I want to upload an official FIFA World Cup match report PDF, so that the application can extract the relevant match data for analysis.

#### Acceptance Criteria

1. THE System SHALL provide a file upload interface that accepts PDF files.
2. WHEN a PDF file is uploaded, THE PDF_Parser SHALL validate that the file is greater than 0 bytes, not password-protected, and contains at least one page before processing.
3. IF a non-PDF file is submitted, THEN THE System SHALL display an error message indicating that only PDF files are accepted.
4. IF the uploaded PDF file exceeds 50 MB, THEN THE System SHALL reject the file and display an error message stating the 50 MB size limit.
5. WHEN a valid PDF has passed all validation checks (correct file type, non-empty, readable, within size limit), THE System SHALL display a progress indicator while the PDF_Parser processes the file, and update the indicator to a success state upon completion.
6. IF the PDF_Parser encounters a runtime failure while processing a valid PDF, THEN THE System SHALL display an error message identifying the failure and allow the user to re-upload without restarting the application.

---

### Requirement 2: Match Data Extraction

**User Story:** As a user, I want the application to extract match data from the uploaded PDF, so that I have accurate squads and statistics to work with.

#### Acceptance Criteria

1. WHEN a valid Match_Report PDF is processed, THE PDF_Parser SHALL extract the Starting_Lineup for both teams, including each Player's name, squad number, and position.
2. WHEN a valid Match_Report PDF is processed, THE PDF_Parser SHALL extract the list of substitute players for both teams, including each substitute Player's name, squad number (1–99), and position.
3. WHEN a valid Match_Report PDF is processed, THE PDF_Parser SHALL extract all Match_Events of the following types: goals, yellow cards, red cards, and substitutions — each including the event type, minute (1–120), and associated Player name.
4. WHEN a valid Match_Report PDF is processed, THE PDF_Parser SHALL extract the following Match_Statistics for both teams: possession percentage, shots on target, total shots, passes, and fouls.
5. IF the PDF_Parser cannot locate one or more expected data fields in the uploaded PDF, THEN THE System SHALL extract all available fields, display a descriptive error message identifying each missing field by name, and prevent the user from proceeding until the missing fields are resolved or explicitly acknowledged.
6. WHEN extraction is complete, THE System SHALL display a summary confirming: both team names, the player count for each team's Starting_Lineup and substitute list, the total number of Match_Events extracted, and whether all five Match_Statistics fields are present for each team.

---

### Requirement 3: Match Data Round-Trip Integrity

**User Story:** As a developer, I want extracted match data to be consistently serializable and deserializable, so that data integrity is maintained throughout the application pipeline.

#### Acceptance Criteria

1. THE System SHALL serialize extracted Match_Data into JSON, mapping team names to string fields, Starting_Lineup and substitute players to ordered arrays, Match_Events to an ordered array of event objects, and Match_Statistics to a numeric fields object.
2. WHEN a Match_Data object is serialized to JSON and then deserialized back, THE resulting Match_Data object SHALL be type-and-content equal to the original, with all list orderings preserved.
3. WHEN Match_Data is deserialized, THE System SHALL validate that: both team name fields are non-empty strings; each Starting_Lineup contains between 1 and 11 player entries; each Match_Event object contains a type, minute, and player name; and all Match_Statistics values are non-negative numbers.
4. IF deserialized Match_Data fails any validation rule in criterion 3, THEN THE System SHALL reject the deserialized object, display an error identifying the failing field(s), and produce no partial Match_Data object.

---

### Requirement 4: Lineup Editing

**User Story:** As a user, I want to modify the starting lineup of either team, so that I can simulate what would have happened with a different squad selection.

#### Acceptance Criteria

1. WHEN Match_Data has been successfully extracted, THE Lineup_Editor SHALL display the Starting_Lineup for both teams in either a visual formation layout or a list layout.
2. THE Lineup_Editor SHALL allow the user to swap any player in the Starting_Lineup with any substitute player from the same team's squad.
3. WHEN the user adds a player not present in the original squad, THE Lineup_Editor SHALL accept a name between 1 and 100 characters and a position value of one of: GK, DEF, MID, or FWD, and add that player to the Starting_Lineup in place of the selected outgoing player.
4. WHILE editing a lineup, THE Lineup_Editor SHALL enforce that the Starting_Lineup always contains exactly eleven players per team.
5. IF the user attempts to submit a lineup with fewer or more than eleven players for either team, THEN THE Lineup_Editor SHALL display an error message identifying the affected team and the current player count, and prevent the prediction from running.
6. WHEN the user activates the reset control, THE Lineup_Editor SHALL restore the Starting_Lineup for both teams to the original extracted values, discarding all swaps made in the current editing session.
7. WHEN a player swap is made, THE Lineup_Editor SHALL apply a distinct visual marker to each changed player entry; WHEN a swap is restored to the original, THE Lineup_Editor SHALL remove that visual marker.

---

### Requirement 5: Match Outcome Prediction

**User Story:** As a user, I want the application to predict how the match would have turned out with my modified lineup, so that I can explore "what if" scenarios.

#### Acceptance Criteria

1. WHEN the user submits a modified lineup, THE Prediction_Engine SHALL generate a Predicted_Outcome using the altered Starting_Lineup and the extracted Match_Data as inputs.
2. THE Prediction_Engine SHALL produce a predicted scoreline (non-negative integer goals per team) as part of the Predicted_Outcome.
3. THE Prediction_Engine SHALL include in the Predicted_Outcome at least three contributing factors, where each factor states: the attribute name (e.g., "positional strength"), the direction of influence (positive or negative), and a percentage magnitude between 1% and 100%.
4. WHEN the original Starting_Lineup is submitted without modification, THE Prediction_Engine SHALL produce a Predicted_Outcome where the win/draw/loss result matches the actual match result AND the predicted goals per team are each within ±1 of the actual goals scored, accompanied by a confidence score expressed as a percentage between 0% and 100%.
5. WHILE the Prediction_Engine is processing, THE System SHALL display a progress indicator and disable the submit control to prevent duplicate prediction submissions.
6. IF the Prediction_Engine encounters an internal error during simulation, THEN THE System SHALL prevent prediction generation, display an error message that identifies the failed operation and instructs the user to retry, and retain the submitted lineup so the user can retry without re-uploading the PDF.

---

### Requirement 6: Predicted Outcome Display

**User Story:** As a user, I want to see the predicted match result clearly presented, so that I can understand the impact of my lineup changes.

#### Acceptance Criteria

1. WHEN a Predicted_Outcome is available, THE System SHALL display the predicted scoreline in a dedicated section positioned above all other match details, formatted as "Team A N – M Team B" alongside the actual result in the same format.
2. THE System SHALL display between 3 and 5 contributing factors identified by the Prediction_Engine, each rendered as a natural-language sentence describing the attribute, its direction, and its percentage magnitude.
3. THE System SHALL display the modified Starting_Lineup used to generate the Predicted_Outcome, with each changed player entry marked with a distinct visual marker that differentiates it from unchanged entries.
4. THE System SHALL display the confidence score as a numeric percentage (0–100%) adjacent to the predicted scoreline.
5. WHEN a Predicted_Outcome is displayed, THE System SHALL provide a control that allows the user to return to the Lineup_Editor to make further modifications without re-uploading the PDF.
6. IF a Predicted_Outcome is unavailable due to a Prediction_Engine error, THEN THE System SHALL display an error message in place of the result section and provide a retry control.

---

### Requirement 7: Session and State Management

**User Story:** As a user, I want my uploaded match data and lineup edits to persist during my session, so that I can iterate on predictions without repeating previous steps.

#### Acceptance Criteria

1. WHILE a user session is active, THE System SHALL retain the extracted Match_Data so that the user does not need to re-upload the PDF between predictions.
2. WHILE a user session is active, THE System SHALL retain the most recently edited lineup so that the user can resume editing from where they left off.
3. WHEN the user activates the clear session control, THE System SHALL display a confirmation prompt before clearing all Match_Data and lineup edits and returning the application to the initial upload state.
4. WHEN the user confirms the clear action, THE System SHALL remove all Match_Data and lineup edits and return the application to the initial upload state.
5. IF a user session has been inactive for 30 consecutive minutes, THEN THE System SHALL display a notification informing the user that their session has expired and that all session data has been cleared, and prompt them to re-upload a PDF.
6. IF the page is refreshed, THEN THE System SHALL display a notification informing the user that session data has been cleared and prompt them to re-upload a PDF.
