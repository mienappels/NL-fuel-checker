import logging
from datetime import timedelta
import voluptuous as vol

from homeassistant.components.sensor import SensorEntity
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
    CoordinatorEntity,
)
import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import PLATFORM_SCHEMA

from .independer import IndependerSource
from .pompwijzer import PompwijzerSource
from .anwb import AnwbSource

_LOGGER = logging.getLogger(__name__)

DOMAIN = "nl_fuel_checker"

CONF_POSTAL_CODE = "postal_code"
CONF_FUEL_TYPE = "fuel_type"
CONF_RANGE = "range"
CONF_LIMIT = "limit"
CONF_SOURCE = "source"

FUEL_TYPES = [
    "euro95",
    "euro98",
    "diesel",
    "lpg",
    "cng",
    "biodiesel",
    "premium_benzine",
    "premium_diesel",
]
SOURCES = ["independer", "pompwijzer", "anwb"]
SOURCE_FUEL_TYPES = {
    "independer": set(FUEL_TYPES),
    "pompwijzer": {"euro95", "euro98", "diesel"},
    "anwb": {"euro95", "euro98", "diesel", "lpg", "premium_diesel", "cng"},
}

FUEL_TYPE_NAMES = {"cng": "CNG"}


def validate_source_fuel(config):
    source = config[CONF_SOURCE]
    fuel_type = config[CONF_FUEL_TYPE]
    supported_fuels = SOURCE_FUEL_TYPES[source]

    if fuel_type not in supported_fuels:
        raise vol.Invalid(
            f"Bron '{source}' ondersteunt uitsluitend "
            f"{sorted(supported_fuels)}. Ongeldige brandstof: '{fuel_type}'."
        )

    return config


PLATFORM_SCHEMA = vol.All(
    PLATFORM_SCHEMA.extend(
        {
            vol.Required(CONF_POSTAL_CODE): cv.string,
            vol.Optional(CONF_FUEL_TYPE, default="euro95"): vol.In(FUEL_TYPES),
            vol.Optional(CONF_SOURCE, default="independer"): vol.In(SOURCES),
            vol.Optional(CONF_RANGE, default=5): cv.positive_int,
            vol.Optional(CONF_LIMIT, default=1): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=5)
            ),
        }
    ),
    validate_source_fuel,
)

SCAN_INTERVAL = timedelta(hours=4)


async def async_setup_platform(hass, config, asyncAddEntities, discoveryInfo=None):
    postalCode = config[CONF_POSTAL_CODE]
    fuelType = config[CONF_FUEL_TYPE]
    searchRange = config[CONF_RANGE]
    resultLimit = config[CONF_LIMIT]
    sourceName = config[CONF_SOURCE]

    httpClient = async_get_clientsession(hass)

    if sourceName == "independer":
        dataSource = IndependerSource(httpClient, postalCode, fuelType, searchRange)
    elif sourceName == "anwb":
        dataSource = AnwbSource(httpClient, postalCode, fuelType, searchRange)
    elif sourceName == "pompwijzer":
        dataSource = PompwijzerSource(httpClient, postalCode, fuelType, searchRange)
    else:
        raise ValueError(f"Onbekende bron: {sourceName}")

    dataCoordinator = NlFuelCoordinator(
        hass, dataSource, postalCode, fuelType, sourceName
    )

    try:
        await dataCoordinator.async_refresh()
    except UpdateFailed as errorMessage:
        raise PlatformNotReady(
            f"Fout bij eerste keer ophalen van data: {errorMessage}"
        ) from errorMessage

    if not dataCoordinator.last_update_success:
        raise PlatformNotReady("Fout bij eerste keer ophalen van data")

    entities = []
    for rank in range(resultLimit):
        entities.append(
            NlFuelSensor(dataCoordinator, postalCode, fuelType, rank, sourceName)
        )

    asyncAddEntities(entities)


class NlFuelCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, dataSource, postalCode, fuelType, sourceName):
        self.dataSource = dataSource
        self.postalCode = postalCode
        self.fuelType = fuelType
        self.sourceName = sourceName

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{sourceName}",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        try:
            return await self.dataSource.fetchPrices()
        except Exception as errorMessage:
            raise UpdateFailed(
                f"Fout bij ophalen van data: {errorMessage}"
            ) from errorMessage


class NlFuelSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, postalCode, fuelType, rank, sourceName):
        super().__init__(coordinator)
        self.postalCode = postalCode
        self.fuelType = fuelType
        self.rank = rank
        self.sourceName = sourceName

        displayRank = self.rank + 1

        fuelName = FUEL_TYPE_NAMES.get(fuelType, fuelType.capitalize())
        self._attr_name = (
            f"{sourceName.capitalize()} {fuelName} ({postalCode}) #{displayRank}"
        )
        self._attr_unique_id = f"nlfuel_{sourceName}_{postalCode.replace(' ', '')}_{fuelType}_{displayRank}".lower()
        self._attr_icon = "mdi:gas-station"
        self._attr_native_unit_of_measurement = "€/L"

    @property
    def native_value(self):
        gasStations = self.coordinator.data
        if gasStations and len(gasStations) > self.rank:
            return gasStations[self.rank].get("price")
        return None

    @property
    def extra_state_attributes(self):
        gasStations = self.coordinator.data
        if gasStations and len(gasStations) > self.rank:
            stationData = gasStations[self.rank]
            return {
                "Bron": self.sourceName.capitalize(),
                "Tankstation": stationData.get("name"),
                "Merk": stationData.get("brand"),
                "Afstand (km)": stationData.get("distanceKm"),
                "Laatst Geüpdatet": stationData.get("lastUpdated"),
                "Adres": f"{stationData.get('address')}, {stationData.get('city')}",
                "latitude": stationData.get("latitude"),
                "longitude": stationData.get("longitude"),
                "Rang": self.rank + 1,
            }
        return {"Fout": "Niet genoeg tankstations gevonden."}
