from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import pytz
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
import pandas as pd

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tower_jumps.db'
db = SQLAlchemy(app)

class LocationData(db.Model):
    """Enhanced location data model with additional fields for quality metrics."""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(100))
    activity = db.Column(db.String(100))
    accuracy = db.Column(db.Float)
    ping_time = db.Column(db.Time)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    accuracy_level = db.Column(db.Integer)
    signal_strength = db.Column(db.Float)
    timezone = db.Column(db.String(50))

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': datetime.combine(self.date, self.ping_time).isoformat(),
            'location': self.location,
            'activity': self.activity,
            'accuracy': self.accuracy,
            'coordinates': {'latitude': self.latitude, 'longitude': self.longitude},
            'accuracy_level': self.accuracy_level,
            'signal_strength': self.signal_strength,
            'timezone': self.timezone
        }

class LocationAnalyzer:
    """Handles location analysis and confidence calculations for any region transitions."""

    def __init__(self):
        self.time_window = timedelta(minutes=5)  # Window for grouping nearby readings
        self.region_cache = {}  # Cache for storing discovered region mappings

    def analyze_transitions(self, readings: List[LocationData]) -> List[Dict]:
        """
        Analyzes location readings to detect region transitions and calculate confidence levels.
        This method works with any regions present in the data, without requiring predefined borders.
        """
        if not readings:
            return []

        analysis_results = []
        current_window = []
        current_region = None

        for reading in readings:
            region = self.extract_region(reading.location)

            # Skip readings without region information
            if not region:
                continue

            # Check if we should start a new window
            if (current_window and
                (region != current_region or
                 reading.date - current_window[-1].date > self.time_window)):

                # Process current window
                if current_window:
                    confidence = self.calculate_confidence(current_window)
                    analysis_results.append({
                        'start_time': current_window[0].date.isoformat(),
                        'end_time': current_window[-1].date.isoformat(),
                        'region': current_region,
                        'confidence': confidence,
                        'readings_count': len(current_window),
                        'average_accuracy': np.mean([r.accuracy for r in current_window if r.accuracy]),
                        'transition_type': 'region_change' if region != current_region else 'time_gap'
                    })

                current_window = []
                current_region = region

            current_window.append(reading)
            current_region = region

        # Process final window
        if current_window:
            confidence = self.calculate_confidence(current_window)
            analysis_results.append({
                'start_time': current_window[0].date.isoformat(),
                'end_time': current_window[-1].date.isoformat(),
                'region': current_region,
                'confidence': confidence,
                'readings_count': len(current_window),
                'average_accuracy': np.mean([r.accuracy for r in current_window if r.accuracy]),
                'transition_type': 'final_period'
            })

        return analysis_results

    def calculate_confidence(self, readings: List[LocationData]) -> float:
        """
        Calculate confidence level based on multiple factors.
        Returns a value between 0 and 100, or 0 if calculation isn't possible.
        """
        if not readings:
            return 0.0

        try:
            # Determine base confidence based on accuracy
            accuracies = [r.accuracy for r in readings if r.accuracy is not None]
            avg_accuracy = np.mean(accuracies)

            if accuracies:
                # Adjust base confidence based on accuracy ranges
                if avg_accuracy >= 1000:  # Poor accuracy
                    base_confidence = 30.0  # Lower base for poor accuracy
                elif avg_accuracy >= 500:  # Fair accuracy
                    base_confidence = 40.0
                else:  # Good accuracy
                    base_confidence = 50.0
            else:
                base_confidence = 40.0  # Default if no accuracy data

            # Factor 1: Consecutive readings (scaled based on accuracy)
            if avg_accuracy >= 1000:
                consecutive_bonus = min(len(readings) * 1, 10)  # Reduced bonus for poor accuracy
            else:
                consecutive_bonus = min(len(readings) * 2, 20)

            # Factor 2: Accuracy contribution (scaled based on accuracy ranges)
            if accuracies:
                if avg_accuracy >= 1000:
                    accuracy_bonus = max(0, 10 * (1 - ((avg_accuracy - 1000) / 1000)))  # Smaller bonus for poor accuracy
                else:
                    accuracy_bonus = max(0, 30 * (1 - (min(avg_accuracy, 1000) / 1000)))  # Normal bonus for good accuracy
            else:
                accuracy_bonus = 0

            # Factor 3: Time consistency (up to 20%)
            if len(readings) > 1:
                time_gaps = []
                for i in range(1, len(readings)):
                    gap = abs((readings[i].date - readings[i-1].date).total_seconds())
                    time_gaps.append(gap)
                avg_gap = np.mean(time_gaps)
                # Scale time bonus - shorter gaps are better
                # Consider gaps <60s excellent, >600s poor
                time_bonus = max(0, 20 * (1 - (min(avg_gap, 600) / 600)))
            else:
                time_bonus = 0

            total_confidence = min(base_confidence + consecutive_bonus +
                                 accuracy_bonus + time_bonus, 100)

            return round(max(0, total_confidence), 2)

        except Exception as e:
            print(f"Error calculating confidence: {e}")
            return 0.0

    def extract_region(self, location_str: str) -> Optional[str]:
        """
        Extracts and normalizes region information from location string using dynamic mappings.
        """
        if not location_str:
            return None

        # Normalize the string
        location_str = location_str.upper().strip()

        # Split by common delimiters
        parts = [p.strip() for p in location_str.replace('-', ',').replace('/', ',').split(',')]

        # Check each part against our dynamic mappings
        for part in reversed(parts):
            for canonical_name, variations in self.region_cache.items():
                if part in variations:
                    return canonical_name

        # If no mapping found, take the last non-empty part
        filtered_parts = [p for p in reversed(parts) if p]
        return filtered_parts[0] if filtered_parts else None


@app.route('/api/locations', methods=['GET'])
def get_locations():
    """
    Enhanced endpoint to retrieve location data with advanced filtering and validation.
    Supports filtering by date range, region, activity, and proximity to borders.
    """
    try:
        # Get and validate query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        region = request.args.get('region')
        activity = request.args.get('activity')
        timezone = request.args.get('timezone', 'UTC')

        # Validate timezone
        try:
            tz = pytz.timezone(timezone)
        except pytz.exceptions.UnknownTimeZoneError:
            return jsonify({
                'success': False,
                'error': f'Invalid timezone: {timezone}'
            }), 400

        # Build base query
        query = LocationData.query

        # Apply filters
        if start_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(LocationData.date >= start)
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': f'Invalid start_date format: {start_date}. Use YYYY-MM-DD'
                }), 400

        if end_date:
            try:
                end = datetime.strptime(end_date, '%Y-%m-%d')
                query = query.filter(LocationData.date <= end)
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': f'Invalid end_date format: {end_date}. Use YYYY-MM-DD'
                }), 400

        if region:
            query = query.filter(LocationData.location.like(f'%{region}%'))

        if activity:
            query = query.filter(LocationData.activity == activity)

        # Execute query
        locations = query.order_by(LocationData.date, LocationData.ping_time).all()

        # Convert timestamps to requested timezone
        for location in locations:
            dt = datetime.combine(location.date, location.ping_time)
            dt = pytz.UTC.localize(dt).astimezone(tz)
            location.date = dt.date()
            location.ping_time = dt.time()

        return jsonify({
            'success': True,
            'metadata': {
                'total_records': len(locations),
                'timezone': timezone,
                'filters_applied': {
                    'start_date': start_date,
                    'end_date': end_date,
                    'region': region,
                    'activity': activity
                }
            },
            'data': [location.to_dict() for location in locations]
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/analysis', methods=['GET'])
def analyze_locations():
    """
    Enhanced analysis endpoint that works with any location data without requiring
    predefined border configurations.
    """
    try:
        # Parse date range and timezone
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        timezone = request.args.get('timezone', 'UTC')

        # Validate timezone
        try:
            tz = pytz.timezone(timezone)
        except pytz.exceptions.UnknownTimeZoneError:
            return jsonify({
                'success': False,
                'error': f'Invalid timezone: {timezone}'
            }), 400

        # Query locations with optional date filtering
        query = LocationData.query.order_by(LocationData.date, LocationData.ping_time)
        if start_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(LocationData.date >= start)
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': f'Invalid start_date format: {start_date}. Use YYYY-MM-DD'
                }), 400

        if end_date:
            try:
                end = datetime.strptime(end_date, '%Y-%m-%d')
                query = query.filter(LocationData.date <= end)
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': f'Invalid end_date format: {end_date}. Use YYYY-MM-DD'
                }), 400

        locations = query.all()

        # Create analyzer and process locations
        analyzer = LocationAnalyzer()
        analysis_results = analyzer.analyze_transitions(locations)

        # Extract unique regions from the analysis
        unique_regions = sorted(list(set(result['region'] for result in analysis_results)))

        # Calculate summary statistics
        total_readings = len(locations)
        region_counts = {}
        for result in analysis_results:
            region = result['region']
            region_counts[region] = region_counts.get(region, 0) + result['readings_count']

        # Calculate time spent in each region
        region_durations = {}
        for result in analysis_results:
            region = result['region']
            start_time = datetime.fromisoformat(result['start_time'])
            end_time = datetime.fromisoformat(result['end_time'])
            duration = (end_time - start_time).total_seconds() / 3600  # Convert to hours
            region_durations[region] = region_durations.get(region, 0) + duration

        # Prepare the response data
        response_data = {
            'success': True,
            'analysis': [
                {
                    'start_time': result['start_time'],
                    'end_time': result['end_time'],
                    'region': result['region'],
                    'confidence': 0.0 if np.isnan(result['confidence']) else result['confidence'],
                    'readings_count': result['readings_count'],
                    'average_accuracy': 0.0 if np.isnan(result['average_accuracy']) else round(result['average_accuracy'], 2),
                    'transition_type': result['transition_type']
                }
                for result in analysis_results
            ],
            'metadata': {
                'total_readings': total_readings,
                'unique_regions': unique_regions,
                'region_statistics': {
                    region: {
                        'reading_count': region_counts.get(region, 0),
                        'hours_spent': round(region_durations.get(region, 0), 2),
                        'percentage_of_readings': round(region_counts.get(region, 0) / total_readings * 100, 2)
                    } for region in unique_regions
                },
                'timezone': timezone,
                'date_range': {
                    'start': min((datetime.combine(loc.date, loc.ping_time)).isoformat()
                               for loc in locations) if locations else None,
                    'end': max((datetime.combine(loc.date, loc.ping_time)).isoformat()
                             for loc in locations) if locations else None
                }
            }
        }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

def init_db():
    """Initialize database with enhanced data loading and validation."""
    with app.app_context():
        db.create_all()
        if LocationData.query.first() is None:
            load_initial_data()

def load_initial_data():
    """Load and validate initial data with enhanced error handling."""
    try:
        df = pd.read_csv('TowerJumpsDataSet.csv')

        # Validate required columns
        required_columns = ['date', 'location', 'latitude', 'longitude', 'accuracy']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {missing_columns}")

        # Process and validate each row
        for _, row in df.iterrows():
            try:
                # Parse and validate datetime
                date_obj = pd.to_datetime(row['date'])

                # Calculate signal strength from accuracy level
                accuracy_level = row.get('accuracy.1')
                # Transform accuracy level to signal strength (0-100 scale)
                if accuracy_level is not None:
                    try:
                        accuracy_val = float(accuracy_level)
                        # Enhanced signal strength calculation:
                        # - Excellent (90-100): accuracy <= 10m
                        # - Very Good (80-89): accuracy <= 50m
                        # - Good (70-79): accuracy <= 100m
                        # - Fair (50-69): accuracy <= 500m
                        # - Poor (20-49): accuracy <= 2000m
                        # - Very Poor (1-19): accuracy > 2000m
                        if accuracy_val <= 10:
                            signal_strength = 90 + min(10, 10 - accuracy_val)
                        elif accuracy_val <= 50:
                            signal_strength = 80 + min(9, (50 - accuracy_val) / 4.5)
                        elif accuracy_val <= 100:
                            signal_strength = 70 + min(9, (100 - accuracy_val) / 5.6)
                        elif accuracy_val <= 500:
                            signal_strength = 50 + min(19, (500 - accuracy_val) / 21.1)
                        elif accuracy_val <= 2000:
                            signal_strength = 20 + min(29, (2000 - accuracy_val) / 51.7)
                        else:
                            signal_strength = max(1, 20 - (accuracy_val - 2000) / 500)

                        signal_strength = round(signal_strength, 2)
                    except (ValueError, TypeError):
                        signal_strength = None
                else:
                    signal_strength = None

                # Create location data with validation
                location_data = LocationData(
                    date=date_obj.date(),
                    location=row['location'],
                    activity=row.get('activity'),
                    accuracy=float(row['accuracy']),
                    ping_time=date_obj.time(),
                    latitude=float(row['latitude']),
                    longitude=float(row['longitude']),
                    accuracy_level=accuracy_level,
                    signal_strength=signal_strength,
                    timezone='UTC'  # Default timezone
                )
                db.session.add(location_data)

            except (ValueError, TypeError) as e:
                print(f"Error processing row: {row}\nError: {e}")
                continue

        db.session.commit()

    except Exception as e:
        print(f"Error loading initial data: {e}")
        db.session.rollback()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
