import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from .source import FuelSource

apiBase = "https://api.pompwijzer.nl/api"

recentMaxMs = 24 * 3_600_000
clockToleranceMs = 5 * 60_000
futureEvidenceMs = 30 * 60_000


class PompwijzerSource(FuelSource):
    def __init__(self, session, postalCode, fuelType, searchRange):
        super().__init__(session, postalCode, fuelType, searchRange)
        self.lat = None
        self.lon = None
        self.serverNowMs = None
        self.indexCache = None
        self.supportedFuels = ["euro95", "euro98", "diesel"]
        if self.fuelType not in self.supportedFuels:
            raise ValueError(f"Bron 'pompwijzer' ondersteunt uitsluitend {self.supportedFuels}. Ongeldige keuze: '{self.fuelType}'.")

    async def getJson(self, url, trackServerTime=False):
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }
        async with self.session.get(url, headers=headers) as response:
            response.raise_for_status()
            if trackServerTime and response.headers.get("Date"):
                self.serverNowMs = int(parsedate_to_datetime(response.headers["Date"]).timestamp() * 1000)
            return await response.json()

    async def fetchCoordinates(self):
        encodedAddress = quote(self.postalCode.replace(" ", ""))
        url = f"https://nominatim.openstreetmap.org/search?q={encodedAddress}&countrycodes=nl&format=json&limit=1"
        headers = {"User-Agent": "NlFuelChecker/1.0"}
        async with asyncio.timeout(10):
            response = await self.session.get(url, headers=headers)
            response.raise_for_status()
            data = await response.json()
            if data:
                self.lat = float(data[0]["lat"])
                self.lon = float(data[0]["lon"])
            else:
                raise Exception(f"Kan geen coördinaten vinden voor: {self.postalCode}")

    async def loadSnapshot(self):
        for attempt in range(2):
            version = await self.getJson(f"{apiBase}/version", trackServerTime=True)
            indexHash = version["index"]
            pricesHash = version["prices"]

            needIndex = self.indexCache is None or self.indexCache[0] != indexHash
            tasks = [self.getJson(f"{apiBase}/v/{pricesHash}/prices.{self.fuelType}.all.json")]
            if needIndex:
                tasks.append(self.getJson(f"{apiBase}/v/{indexHash}/index.all.json"))
            results = await asyncio.gather(*tasks)

            prices = results[0]
            if needIndex:
                index = results[1]
                self.indexCache = (indexHash, index, {stationId: position for position, stationId in enumerate(index["id"])})
            _, index, idToPosition = self.indexCache

            if prices.get("index") != index.get("v"):
                continue
            stationCount = len(index["id"])
            if any(len(prices[column]) != stationCount for column in ("price", "ts", "flags")):
                raise Exception("Pompwijzer: prijsbestand past niet bij de stationslijst.")
            return index, idToPosition, prices

        raise Exception("Pompwijzer: stationslijst en prijzen komen niet overeen.")

    @staticmethod
    def observedAtMs(tsMs, flags, nowMs):
        if flags & 1:
            return None
        evidenceMs = tsMs - ((flags >> 24) & 0xFF) * 600_000
        effectiveNowMs = max(nowMs, evidenceMs) if evidenceMs - nowMs <= futureEvidenceMs else nowMs
        freshMinutes = (flags >> 8) & 0xFFFF
        if freshMinutes and effectiveNowMs >= tsMs + freshMinutes * 60_000:
            return None
        ageMs = effectiveNowMs - evidenceMs
        if ageMs < -clockToleranceMs or ageMs >= recentMaxMs:
            return None
        return evidenceMs

    async def fetchPrices(self):
        if self.lat is None or self.lon is None:
            await self.fetchCoordinates()

        urlDistances = f"{apiBase}/location-distances?location={self.lon}%2C{self.lat}&radius_km={self.searchRange}"

        async with asyncio.timeout(20):
            jsonDistances, snapshot = await asyncio.gather(
                self.getJson(urlDistances),
                self.loadSnapshot()
            )
        index, idToPosition, prices = snapshot

        nowMs = self.serverNowMs or int(datetime.now(timezone.utc).timestamp() * 1000)

        validStations = []
        for distanceInfo in jsonDistances.get("stations", []):
            position = idToPosition.get(distanceInfo["station_id"])
            if position is None:
                continue
            price = prices["price"][position]
            tsMs = prices["ts"][position]
            flags = prices["flags"][position]
            if price is None or tsMs is None or flags is None or price <= 0:
                continue
            observedMs = self.observedAtMs(tsMs, flags, nowMs)
            if observedMs is None:
                continue

            brandIndex = index["brand"][position]
            drivingDistanceKm = distanceInfo.get("driving_distance", 0) / 1000
            validStations.append({
                "name": index["name"][position],
                "brand": index["brands"][brandIndex]["name"] if brandIndex is not None else None,
                "address": index["address"][position],
                "city": index["city"][position],
                "price": price,
                "distanceKm": round(drivingDistanceKm, 2),
                "lastUpdated": datetime.fromtimestamp(observedMs / 1000, tz=timezone.utc).isoformat(),
                "latitude": index["lat"][position],
                "longitude": index["lon"][position]
            })
        validStations.sort(key=lambda s: (s["price"], s["distanceKm"]))
        return validStations