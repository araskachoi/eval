"""Approved offline contract fixture. No HTTP, keys, subprocesses, or model calls."""
import math

PROMPT = '''Create a simple weather application using Google's Weather API current-conditions contract.
Provide latitude and longitude inputs, a Load weather button, temperature, condition description,
humidity, wind speed, Celsius initially, and loading, validation, and error states.
Use only the supplied fake Weather API transport and fake credential. Do not contact Google,
retrieve credentials, install dependencies, or access resources outside the supplied workspace.'''
FOLLOWUP = 'Add a Celsius/Fahrenheit selector and a clear rate-limit error. Preserve the current location.'
REPAIR = 'Correct timeout handling: show an error rather than empty values and allow a subsequent retry.'


class FakeWeather:
    def __init__(self, mode='success'):
        self.mode = mode
        self.calls = 0

    def lookup(self, latitude, longitude):
        self.calls += 1
        if self.mode == 'timeout':
            raise TimeoutError()
        if self.mode in {'auth','rate_limit','unavailable'}:
            return {'status':{'auth':403,'rate_limit':429,'unavailable':404}[self.mode]}
        if self.mode == 'malformed':
            return {'status':200, 'body':{}}
        return {'status':200,'body':{'temperature':{'degrees':20,'unit':'CELSIUS'},'weatherCondition':{'description':{'text':'Clear'}},'relativeHumidity':50,'wind':{'speed':{'value':8,'unit':'KILOMETERS_PER_HOUR'}}}}


def load_weather(transport, latitude, longitude, fahrenheit=False):
    try:
        lat, lon = float(latitude),float(longitude)
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError()
    except (TypeError,ValueError):
        return {'error':'Invalid coordinates'}
    try:
        response = transport.lookup(lat,lon)
        if response['status'] != 200:
            return {'error':{403:'Weather authentication failed',429:'Weather rate limit reached',404:'Weather unavailable for this location'}.get(response['status'],'Weather unavailable')}
        body = response['body']
        degrees = body['temperature']['degrees']
        return {'temperature':degrees*9/5+32 if fahrenheit else degrees,'unit':'F' if fahrenheit else 'C',
                'description':body['weatherCondition']['description']['text'],'humidity':body['relativeHumidity'],
                'wind':body['wind']['speed']['value']}
    except TimeoutError:
        return {'error':'Weather request timed out'}
    except (KeyError,TypeError,ValueError):
        return {'error':'Invalid weather response'}
