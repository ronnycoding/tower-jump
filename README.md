# Location Analysis System

A sophisticated Flask-based REST API application that analyzes location data from mobile devices to determine user presence in different geographical regions. The system processes location data from various sources, including cell tower triangulation, and provides confidence levels for location determinations.

## Understanding the System

This application serves as a powerful tool for analyzing location data across any geographical region. While it was initially inspired by state boundary analysis, it has been designed to work with any location format, making it suitable for various use cases such as:

- Cross-border movement analysis
- Regional presence detection
- Location-based activity tracking
- Geographical transition pattern analysis

The system processes raw location data and provides insights about where a user spent time, including confidence levels based on the consistency of readings.

## Prerequisites

- Python 3.12 or higher
- pip package manager
- Virtual environment (recommended)

## Installation

First, let's set up our development environment. Open your terminal and follow these steps:

1. Clone the repository:
```bash
git clone https://github.com/yourusername/location-analysis.git
cd location-analysis
```

2. Create and activate a virtual environment:
```bash
python -m venv venv

source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

The application uses SQLite as its database engine for simplicity and portability. When you run the application for the first time, it will:

1. Create a new database file named `tower_jumps.db`
2. Initialize the required tables
3. Import data from `TowerJumpsDataSet.csv` if present

Place your CSV data file in the root directory with the following columns:
- date: Date of the reading
- location: Location string (flexible format)
- activity: Activity type
- accuracy: Accuracy score
- ping_time: Time of the reading
- latitude: Geographical latitude
- longitude: Geographical longitude
- accuracy_level: Secondary accuracy indicator

## Running the Application

Start the Flask server:
```bash
python app.py
```

The server will begin running at `http://localhost:5000`

## API Endpoints and Usage

### 1. Retrieve Location Data
The locations endpoint provides access to raw location data with flexible filtering options.

```bash
# Get all locations
curl http://localhost:5000/api/locations

# Filter by specific region
curl http://localhost:5000/api/locations?region=California

# Filter by date
curl http://localhost:5000/api/locations?date=2024-01-01

# Filter by activity
curl http://localhost:5000/api/locations?activity=stationary

# Combine multiple filters
curl "http://localhost:5000/api/locations?region=California&date=2024-01-01"
```

Example response:
```json
{
    "success": true,
    "count": 25,
    "data": [
        {
            "id": 1,
            "date": "2024-01-01",
            "location": "San Francisco, California",
            "activity": "stationary",
            "accuracy": 95,
            "ping_time": "09:00:00",
            "latitude": 37.7749,
            "longitude": -122.4194,
            "accuracy_level": 1
        }
    ]
}
```

### 2. Location Analysis
The analysis endpoint provides processed insights about location patterns and transitions.

```bash
# Get complete analysis
curl http://localhost:5000/api/analysis

# Analyze specific date range
curl "http://localhost:5000/api/analysis?start_date=2024-01-01&end_date=2024-01-31"

# Pretty print the results
curl -s "http://localhost:5000/api/analysis" | python -m json.tool
```

Example response:
```json
{
    "success": true,
    "summary": {
        "total_records": 108,
        "unique_regions": 3,
        "time_periods": 12,
        "date_range": {
            "start": "2024-01-01",
            "end": "2024-01-31"
        }
    },
    "data": [
        {
            "start_time": "2024-01-01 09:00:00",
            "end_time": "2024-01-01 12:00:00",
            "region": "California",
            "confidence": 85,
            "consecutive_readings": 3
        }
    ]
}
```

## Understanding Confidence Levels

The system calculates confidence levels for location determinations using several factors:

1. Base Confidence: Starts at 70% as a baseline
2. Consecutive Readings: Each consecutive reading in the same region adds 5% confidence
3. Maximum Confidence: Capped at 100% to maintain realism

This approach means:
- Single readings start at 70% confidence
- Multiple consecutive readings increase confidence
- Long periods in the same region achieve higher confidence levels
- Transitions between regions reset the consecutive counter

## Error Handling

The API uses consistent error reporting:

- Success responses include: `{"success": true, "data": ...}`
- Error responses include: `{"success": false, "error": "error message"}`
- HTTP status codes indicate the type of error (400 for client errors, 500 for server errors)
