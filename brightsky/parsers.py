import csv
import os
import re
import zipfile

import dateutil.parser
from parsel import Selector

from brightsky.utils import download


class MOSMIXParser:

    URL = (
        'https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_S/'
        'all_stations/kml/MOSMIX_S_LATEST_240.kmz')

    ELEMENTS = {
        'TTT': 'temperature',
        'DD': 'wind_direction',
        'FF': 'wind_speed',
        'RR1c': 'precipitation',
        'SunD1': 'sunshine',
        'PPPP': 'pressure',
    }

    @property
    def path(self):
        filename = os.path.basename(self.URL)
        dirname = os.path.join(os.getcwd(), '.brightsky_cache')
        os.makedirs(dirname, exist_ok=True)
        return os.path.join(dirname, filename)

    def download(self):
        download(self.URL, self.path)

    def get_selector(self):
        with zipfile.ZipFile(self.path) as zf:
            infolist = zf.infolist()
            assert len(infolist) == 1, f'Unexpected zip content in {self.path}'
            with zf.open(infolist[0]) as f:
                sel = Selector(f.read().decode('latin1'), type='xml')
        sel.remove_namespaces()
        return sel

    def parse(self):
        sel = self.get_selector()
        timestamps = self.parse_timestamps(sel)
        for station_sel in sel.css('Placemark'):
            yield from self.parse_station(station_sel, timestamps)

    def parse_timestamps(self, sel):
        return [
            dateutil.parser.parse(ts)
            for ts in sel.css('ForecastTimeSteps > TimeStep::text').extract()]

    def parse_station(self, station_sel, timestamps):
        station_id = station_sel.css('name::text').extract_first()
        records = {
            'timestamp': timestamps,
            'station_id': [station_id] * len(timestamps),
        }
        for element, column in self.ELEMENTS.items():
            values_str = station_sel.css(
                f'Forecast[elementName="{element}"] value::text'
            ).extract_first()
            records[column] = [
                None if row[0] == '-' else float(row[0])
                for row in csv.reader(
                    re.sub(r'\s+', '\n', values_str.strip()).splitlines())
            ]
            assert len(records[column]) == len(timestamps)
        # Turn dict of lists into list of dicts
        return (dict(zip(records, l)) for l in zip(*records.values()))