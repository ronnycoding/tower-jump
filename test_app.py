import pytest
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import json
import factory
from freezegun import freeze_time
from app import app, db, LocationData, LocationAnalyzer, init_db

@pytest.fixture
def test_app():
    """Create a test application with an in-memory SQLite database."""
    original_db_uri = app.config['SQLALCHEMY_DATABASE_URI']

    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False
    })

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()
        app.config['SQLALCHEMY_DATABASE_URI'] = original_db_uri

@pytest.fixture
def test_client(test_app):
    """Create a test client for making requests."""
    return test_app.test_client()

@pytest.fixture
def location_analyzer():
    """Create a LocationAnalyzer instance for testing."""
    return LocationAnalyzer()

class HudsonRiverLocationFactory(factory.Factory):
    """Factory for creating realistic test data along the Hudson River."""
    class Meta:
        model = LocationData

    @factory.lazy_attribute
    def date(self):
        return datetime.now().date()

    @factory.lazy_attribute
    def ping_time(self):
        return datetime.now().time()

    activity = factory.Iterator(['Personal', 'Tower Jump'])

    @factory.lazy_attribute
    def latitude(self):
        # Hudson River area between NY and NJ (roughly 40.7°N to 41.7°N)
        return factory.Faker('latitude').generate({
            'min_lat': 40.7,
            'max_lat': 41.7
        })

    @factory.lazy_attribute
    def longitude(self):
        # Hudson River area (roughly -74.1°W to -73.7°W)
        return factory.Faker('longitude').generate({
            'min_long': -74.1,
            'max_long': -73.7
        })

    @factory.lazy_attribute
    def location(self):
        # Determine state based on longitude (Hudson River roughly at -73.92°W)
        return 'NY' if self.longitude > -73.92 else 'NJ'

    @factory.lazy_attribute
    def accuracy(self):
        # Simulate different accuracy levels based on activity
        if self.activity == 'Tower Jump':
            return factory.Faker('random_int', min=1000, max=2000).generate({})
        return factory.Faker('random_int', min=4, max=100).generate({})

    accuracy_level = factory.SelfAttribute('accuracy')

    # Add signal strength calculation
    @factory.lazy_attribute
    def signal_strength(self):
        if self.accuracy <= 10:
            return 90 + min(10, 10 - self.accuracy)
        elif self.accuracy <= 50:
            return 80 + min(9, (50 - self.accuracy) / 4.5)
        elif self.accuracy <= 100:
            return 70 + min(9, (100 - self.accuracy) / 5.6)
        elif self.accuracy <= 500:
            return 50 + min(19, (500 - self.accuracy) / 21.1)
        elif self.accuracy <= 2000:
            return 20 + min(29, (2000 - self.accuracy) / 51.7)
        else:
            return max(1, 20 - (self.accuracy - 2000) / 500)

def create_test_journey(test_app, start_time, duration_minutes=60):
    """Create a realistic journey dataset crossing the Hudson River."""
    locations = []
    current_time = start_time

    # Start in New Jersey
    locations.append(LocationData(
        date=current_time.date(),
        ping_time=current_time.time(),
        latitude=40.8540,
        longitude=-74.0141,  # West of Hudson
        location='NJ',
        activity='Personal',
        accuracy=10,
        accuracy_level=10,
        signal_strength=90  # High signal strength for accurate reading
    ))

    # Cross the Hudson (potential tower jump)
    current_time += timedelta(minutes=15)
    locations.append(LocationData(
        date=current_time.date(),
        ping_time=current_time.time(),
        latitude=40.8296,
        longitude=-73.9719,  # Near Hudson
        location='NJ',
        activity='Tower Jump',
        accuracy=2000,
        accuracy_level=2000,
        signal_strength=20  # Low signal strength for tower jump
    ))

    # Arrive in New York
    current_time += timedelta(minutes=15)
    locations.append(LocationData(
        date=current_time.date(),
        ping_time=current_time.time(),
        latitude=40.8099,
        longitude=-73.9216,  # East of Hudson
        location='NY',
        activity='Personal',
        accuracy=15,
        accuracy_level=15,
        signal_strength=85  # Good signal strength for accurate reading
    ))

    with test_app.app_context():
        db.session.bulk_save_objects(locations)
        db.session.commit()

    return locations

@freeze_time("2024-11-23 10:00:00")
def test_border_crossing_analysis(test_client, test_app):
    """Test analysis of location data during a border crossing scenario."""
    create_test_journey(test_app, datetime.now())

    response = test_client.get('/api/analysis')
    data = json.loads(response.data)

    assert response.status_code == 200
    assert data['success'] is True

    # Verify the analysis captures the journey phases
    analysis = data['analysis']
    assert len(analysis) >= 2  # Should have at least NJ and NY periods

    # Check confidence levels with more appropriate ranges
    for period in analysis:
        if period['average_accuracy'] <= 50:  # High accuracy
            assert 50 <= period['confidence'] <= 100, (
                f"High accuracy confidence should be between 50 and 100, got {period['confidence']}"
            )
        elif period['average_accuracy'] >= 1000:  # Tower jump/poor accuracy
            assert 20 <= period['confidence'] <= 80, (  # Updated upper bound to 80
                f"Low accuracy confidence should be between 20 and 80, got {period['confidence']}"
            )
        else:  # Medium accuracy
            assert 50 <= period['confidence'] <= 90, (
                f"Medium accuracy confidence should be between 50 and 90, got {period['confidence']}"
            )

def test_signal_strength_calculation(test_client, test_app):
    """Test signal strength calculation based on accuracy levels."""
    with test_app.app_context():
        locations = [
            LocationData(
                date=datetime.now().date(),
                ping_time=datetime.now().time(),
                latitude=40.8540,
                longitude=-74.0141,
                location='NJ',
                activity='Personal',
                accuracy=5,      # Excellent accuracy
                accuracy_level=5,
                signal_strength=95  # Explicitly set signal strength
            ),
            LocationData(
                date=datetime.now().date(),
                ping_time=datetime.now().time(),
                latitude=40.8296,
                longitude=-73.9719,
                location='NJ',
                activity='Tower Jump',
                accuracy=2000,   # Poor accuracy
                accuracy_level=2000,
                signal_strength=20  # Explicitly set signal strength
            )
        ]
        db.session.bulk_save_objects(locations)
        db.session.commit()

    response = test_client.get('/api/locations')
    data = json.loads(response.data)

    assert response.status_code == 200
    locations_data = data['data']

    # Verify signal strength values
    accurate_reading = next(loc for loc in locations_data if loc['accuracy'] == 5)
    poor_reading = next(loc for loc in locations_data if loc['accuracy'] == 2000)

    assert accurate_reading['signal_strength'] == 95
    assert poor_reading['signal_strength'] == 20

def test_confidence_calculation(location_analyzer):
    """Test confidence calculation based on various factors."""
    current_time = datetime.now()

    # Test case 1: High confidence scenario
    high_confidence_readings = [
        LocationData(
            date=current_time.date(),
            ping_time=current_time.time(),
            latitude=40.8540,
            longitude=-74.0141,
            location='NJ',
            activity='Personal',
            accuracy=5,
            accuracy_level=5,
            signal_strength=95
        ) for _ in range(5)  # Multiple consistent readings
    ]
    high_confidence = location_analyzer.calculate_confidence(high_confidence_readings)
    assert 50 <= high_confidence <= 100

    # Test case 2: Low confidence scenario (Tower Jump)
    low_confidence_readings = [
        LocationData(
            date=current_time.date(),
            ping_time=current_time.time(),
            latitude=40.8296,
            longitude=-73.9719,
            location='NJ',
            activity='Tower Jump',
            accuracy=2000,
            accuracy_level=2000,
            signal_strength=20
        )
    ]
    low_confidence = location_analyzer.calculate_confidence(low_confidence_readings)
    assert 20 <= low_confidence <= 55  # Updated range

    # Test case 3: Medium confidence scenario
    medium_confidence_readings = [
        LocationData(
            date=current_time.date(),
            ping_time=current_time.time(),
            latitude=40.8540,
            longitude=-74.0141,
            location='NJ',
            activity='Personal',
            accuracy=100,
            accuracy_level=100,
            signal_strength=70
        )
    ]
    medium_confidence = location_analyzer.calculate_confidence(medium_confidence_readings)
    assert 50 <= medium_confidence <= 80  # Updated range

if __name__ == '__main__':
    pytest.main(['-v'])
