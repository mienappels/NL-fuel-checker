import asyncio
import math
from urllib.parse import quote, urlencode

from .source import FuelSource


API_URL = "https://api.anwb.nl/routing/points-of-interest/v3/all"
GEOCODING_URL = "https://nominatim.openstreetmap.org/search"

FUEL_MAPPING = {
    "euro95": "EURO95",
    "euro98": "EURO98",
    "diesel": "DIESEL",
    "lpg": "AUTOGAS",
    "premium_diesel": "DIESEL_SPECIAL",
}


class AnwbSource(FuelSource):
    def __init__(self, session, postalCode, fuelType, searchRange):
        super().__init__(session, postalCode, fuelType, searchRange)

        self.lat = None
        self.lon = None

        if self.fuelType not in FUEL_MAPPING:
            raise ValueError(
                f"Bron 'anwb' ondersteunt uitsluitend "
                f"{list(FUEL_MAPPING.keys())}. "
                f"Ongeldige keuze: '{self.fuelType}'."
            )

        self.anwbFuelType = FUEL_MAPPING[self.fuelType]

    async def getJson(self, url, headers=None):
        async with self.session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()

    async def fetchCoordinates(self):
        encodedAddress = quote(self.postalCode.replace(" ", ""))

        url = f"{GEOCODING_URL}?q={encodedAddress}&countrycodes=nl&format=json&limit=1"

        headers = {"User-Agent": "NlFuelChecker/1.0"}

        async with asyncio.timeout(10):
            data = await self.getJson(url, headers)

        if not data:
            raise Exception(f"Kan geen coördinaten vinden voor: {self.postalCode}")

        self.lat = float(data[0]["lat"])
        self.lon = float(data[0]["lon"])

    def createBoundingBox(self):
        latRadius = self.searchRange / 111.32

        cosLat = max(abs(math.cos(math.radians(self.lat))), 0.000001)

        lonRadius = self.searchRange / (111.32 * cosLat)

        south = max(-90, self.lat - latRadius)
        north = min(90, self.lat + latRadius)
        west = max(-180, self.lon - lonRadius)
        east = min(180, self.lon + lonRadius)

        return ",".join(
            f"{coordinate:.6f}" for coordinate in (south, west, north, east)
        )

    @staticmethod
    def calculateDistance(lat1, lon1, lat2, lon2):
        earthRadiusKm = 6371.0

        lat1 = math.radians(lat1)
        lon1 = math.radians(lon1)
        lat2 = math.radians(lat2)
        lon2 = math.radians(lon2)

        deltaLat = lat2 - lat1
        deltaLon = lon2 - lon1

        a = (
            math.sin(deltaLat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(deltaLon / 2) ** 2
        )

        return 2 * earthRadiusKm * math.asin(math.sqrt(a))

    async def fetchPrices(self):
        if self.lat is None or self.lon is None:
            await self.fetchCoordinates()

        params = {
            "type-filter": "FUEL_STATION",
            "show-all-pois-along-route-filter": "true",
            "bounding-box-filter": self.createBoundingBox(),
            "fuel-types-filter": self.anwbFuelType,
        }

        url = f"{API_URL}?{urlencode(params)}"

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }

        async with asyncio.timeout(20):
            jsonData = await self.getJson(url, headers)

        stations = jsonData.get("value") or []
        validStations = []

        for station in stations:
            coordinates = station.get("coordinates") or {}
            addressInfo = station.get("address") or {}

            latitude = coordinates.get("latitude")
            longitude = coordinates.get("longitude")

            if latitude is None or longitude is None:
                continue

            latitude = float(latitude)
            longitude = float(longitude)

            distanceKm = self.calculateDistance(
                self.lat,
                self.lon,
                latitude,
                longitude,
            )

            if distanceKm > self.searchRange:
                continue

            fuelPrice = next(
                (
                    price
                    for price in (station.get("prices") or [])
                    if price.get("fuelType") == self.anwbFuelType
                ),
                None,
            )

            if not fuelPrice:
                continue

            priceValue = fuelPrice.get("value")

            try:
                priceValue = float(priceValue)
            except (TypeError, ValueError):
                continue

            if not math.isfinite(priceValue) or priceValue <= 0:
                continue

            validStations.append(
                {
                    "name": station.get("title"),
                    "brand": station.get("brand") or "Onbekend",
                    "address": addressInfo.get("streetAddress", ""),
                    "city": addressInfo.get("city", ""),
                    "price": priceValue,
                    "distanceKm": round(distanceKm, 2),
                    "lastUpdated": station.get("lastUpdated"),
                    "latitude": latitude,
                    "longitude": longitude,
                }
            )

        validStations.sort(
            key=lambda station: (
                station["price"],
                station["distanceKm"],
            )
        )

        return validStations
