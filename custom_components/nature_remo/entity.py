"""Base entities for the Nature Remo integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import NoReturn

from aionatureremo import (
    APPLIANCE_TYPE_AC,
    APPLIANCE_TYPE_FLOOR_HEATER,
    AirconExtra,
    Appliance,
    Device,
    NatureRemoError,
    NatureRemoRateLimitError,
)
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, STALE_POLLS_BEFORE_REMOVAL
from .coordinator import NatureRemoConfigEntry, NatureRemoCoordinator, NatureRemoData

_LOGGER = logging.getLogger(__name__)

type EntityFactory = Callable[[], Entity]
type EntityBuilder = Callable[[NatureRemoData], dict[str, EntityFactory]]
type RetainPredicate = Callable[[NatureRemoData, str], bool]


class StaleIdTracker:
    """Counts consecutive real polls in which an id went missing.

    Deleting a registry entry also deletes the customizations attached to
    it, so one truncated API response must not be enough to trigger it: an
    id only counts as gone after ``STALE_POLLS_BEFORE_REMOVAL`` consecutive
    real polls without it. Optimistic command responses notify the same
    listeners without polling the API, hence the ``poll_count`` guard —
    without it, three commands in a row would evict a live id.
    """

    def __init__(self, coordinator: NatureRemoCoordinator) -> None:
        """Initialize an empty tracker reading polls from the coordinator."""
        self._coordinator = coordinator
        # id -> (poll_count when the miss was counted, misses in a row)
        self._misses: dict[str, tuple[int, int]] = {}

    @callback
    def async_seen(self, key: str) -> None:
        """Reset the streak of an id the API reported again."""
        self._misses.pop(key, None)

    @callback
    def async_record_miss(self, key: str) -> bool:
        """Count one miss for an id and report whether it is now stale."""
        poll_count = self._coordinator.poll_count
        last_poll, misses = self._misses.get(key, (-1, 0))
        if poll_count == last_poll:
            # Already counted for this poll: this pass was triggered by an
            # optimistic update, which says nothing about the id's fate.
            return False
        misses += 1
        if misses < STALE_POLLS_BEFORE_REMOVAL:
            self._misses[key] = (poll_count, misses)
            return False
        self._misses.pop(key, None)
        return True


@callback
def async_manage_platform_entities(
    hass: HomeAssistant,
    entry: NatureRemoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    *,
    domain: Platform,
    build_entities: EntityBuilder,
    retain: RetainPredicate | None = None,
) -> None:
    """Keep one platform's entities in sync with what the API reports.

    Every platform passes a ``build_entities`` callback mapping the unique_id
    of each entity the current data warrants to a factory that builds it
    (called only for ids that are genuinely new). Entities appear as their
    ids do, and — after the grace period of ``StaleIdTracker`` — vanish from
    the entity registry once their ids stay gone: an IR signal or a TV button
    deleted in the Nature app would otherwise leave an orphan that still
    looks available and errors on press.

    Platforms whose membership is value-gated rather than presence-gated (a
    sensor exists only while its reading is in the payload) pass ``retain``
    to keep creation and removal apart: an id it accepts never counts as a
    miss, so only the parent hub/appliance actually going away removes the
    entity.

    Removal candidates come from the entity registry rather than from what
    this run added, so orphans left behind by earlier versions or by previous
    Home Assistant runs are swept as well.
    """
    coordinator = entry.runtime_data
    entity_registry = er.async_get(hass)
    stale = StaleIdTracker(coordinator)
    # Purely add-dedup; the registry above is the source of truth for removal.
    known: set[str] = set()

    @callback
    def _sync_entities() -> None:
        data = coordinator.data
        wanted = build_entities(data)
        if new_ids := [unique_id for unique_id in wanted if unique_id not in known]:
            known.update(new_ids)
            async_add_entities([wanted[unique_id]() for unique_id in new_ids])
        # Ids this platform still owns a registry entry for once the sweep
        # below is done.
        surviving: set[str] = set()
        for registry_entry in er.async_entries_for_config_entry(
            entity_registry, entry.entry_id
        ):
            if registry_entry.domain != domain:
                continue
            unique_id = registry_entry.unique_id
            # An id the platform still wants, or one whose parent is present
            # and only whose reading dropped out, is not missing at all: reset
            # the streak so the grace period always counts from the last time
            # the entity had a reason to exist.
            if unique_id in wanted or (retain is not None and retain(data, unique_id)):
                stale.async_seen(unique_id)
                surviving.add(unique_id)
                continue
            if not stale.async_record_miss(unique_id):
                surviving.add(unique_id)
                continue
            # Look the id up again instead of trusting the snapshot: removing
            # the appliance's device cascades into its entities, so the entry
            # may already be gone by the time this runs.
            entity_id = entity_registry.async_get_entity_id(domain, DOMAIN, unique_id)
            if entity_id is not None:
                # Removal is destructive and irreversible from the user's side
                # (automations referencing the entity break), so it must leave
                # a trace: a wrongful eviction is otherwise indistinguishable
                # from an entity that was never created.
                _LOGGER.info(
                    "Removing %s entity %s (unique_id %s): the Nature API has not "
                    "reported it in %d consecutive polls",
                    domain,
                    entity_id,
                    unique_id,
                    STALE_POLLS_BEFORE_REMOVAL,
                )
                entity_registry.async_remove(entity_id)
        # Forget every id whose entity no longer exists — removed just now,
        # cascaded away with its device, or deleted by the user. Keeping it in
        # `known` would make a returning id invisible until a restart.
        known.intersection_update(wanted.keys() | surviving)

    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


def build_remo_device_info(device: Device) -> DeviceInfo:
    """Build device-registry info for a Remo hardware device (spec 5.4).

    Shared by the entity base and the eager device registration in
    ``async_setup_entry`` so both describe the hub identically.
    """
    model, _, sw_version = device.firmware_version.partition("/")
    device_info = DeviceInfo(
        identifiers={(DOMAIN, device.id)},
        name=device.name,
        manufacturer="Nature",
        model=model or None,
        sw_version=sw_version or None,
        serial_number=device.serial_number,
        configuration_url="https://home.nature.global/",
    )
    if device.mac_address:
        device_info["connections"] = {(CONNECTION_NETWORK_MAC, device.mac_address)}
    return device_info


def build_appliance_device_info(appliance: Appliance) -> DeviceInfo:
    """Build device-registry info for an appliance behind a Remo (spec 5.4).

    Shared by the entity base and the per-poll device registration in
    ``async_setup_entry``: registering from the same builder is what lets a
    nickname edited in the Nature app reach the device registry, and keeps
    the two descriptions from drifting apart.
    """
    model = appliance.model
    device_info = DeviceInfo(
        identifiers={(DOMAIN, appliance.id)},
        name=appliance.nickname,
        manufacturer=model.manufacturer if model else None,
        model=(model.name or model.remote_name) if model else None,
    )
    if appliance.device_id:
        device_info["via_device"] = (DOMAIN, appliance.device_id)
    return device_info


def command_error_message(action: str, err: NatureRemoError) -> str:
    """Compose a command-failure message, surfacing the rate-limit reset.

    Spec 5.5 requires command failures to include the rate-limit reset epoch
    when the API returns HTTP 429; other errors keep the plain message.
    """
    message = f"{action}: {err}"
    if isinstance(err, NatureRemoRateLimitError) and err.reset is not None:
        message = f"{message} (rate limit resets at epoch {err.reset})"
    return message


def raise_command_error(name: str, err: NatureRemoError) -> NoReturn:
    """Raise a translated command failure, surfacing the rate-limit reset.

    Spec 5.5 requires command failures to include the rate-limit reset epoch
    when the API returns HTTP 429; other errors keep the plain message.
    """
    if isinstance(err, NatureRemoRateLimitError) and err.reset is not None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed_rate_limited",
            translation_placeholders={
                "name": name,
                "error": str(err),
                "reset": str(err.reset),
            },
        ) from err
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_failed",
        translation_placeholders={"name": name, "error": str(err)},
    ) from err


class NatureRemoDeviceEntity(CoordinatorEntity[NatureRemoCoordinator]):
    """An entity belonging to a Nature Remo hardware device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NatureRemoCoordinator, device_id: str) -> None:
        """Initialize with device registry info for the Remo hardware."""
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.data.devices[device_id]
        self._last_device = device
        self._attr_device_info = build_remo_device_info(device)

    @property
    def device(self) -> Device:
        """Return the current device data, or the last one seen.

        A hub can vanish from a poll (removed from the account, or a
        truncated response) while service calls and state writes still reach
        the entity; falling back to the last known snapshot keeps those paths
        from raising a bare KeyError. ``available`` is what reports the hub
        as gone.
        """
        device = self.coordinator.data.devices.get(self._device_id)
        if device is not None:
            self._last_device = device
        return self._last_device

    @property
    def available(self) -> bool:
        """Unavailable when the device disappears or reports itself offline.

        ``online`` is three-valued: only newer firmware (Nature-2W3 /
        Remo 2.x / Remo-E-lite) reports it, so None means "not reported"
        and must stay available. An explicit False means the hub is
        unreachable and its last readings are stale.
        """
        if (
            not super().available
            or self._device_id not in self.coordinator.data.devices
        ):
            return False
        return self.device.online is not False


class NatureRemoApplianceEntity(CoordinatorEntity[NatureRemoCoordinator]):
    """An entity belonging to an appliance controlled through a Remo."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NatureRemoCoordinator, appliance_id: str) -> None:
        """Initialize with an appliance device linked to its Remo."""
        super().__init__(coordinator)
        self._appliance_id = appliance_id
        appliance = coordinator.data.appliances[appliance_id]
        self._last_appliance = appliance
        self._attr_device_info = build_appliance_device_info(appliance)

    @property
    def appliance(self) -> Appliance:
        """Return the current appliance data, or the last one seen.

        An appliance can vanish from a poll (deleted in the Nature app, or
        a truncated response), and state writes and service calls still
        reach the entity afterwards; falling back to the last known
        snapshot keeps those paths from raising a bare KeyError.
        ``available`` is what reports the appliance as gone.
        """
        appliance = self.coordinator.data.appliances.get(self._appliance_id)
        if appliance is not None:
            self._last_appliance = appliance
        return self._last_appliance

    @property
    def available(self) -> bool:
        """Unavailable when the appliance disappears from the account."""
        return (
            super().available and self._appliance_id in self.coordinator.data.appliances
        )


EXTRA_TYPE_CHOICE = "choice"
EXTRA_TYPE_TIME = "time"
EXTRA_AVAILABLE = "available"
EXTRA_ON_OFF = frozenset({"on", "off"})


def extras_catalog(appliance: Appliance) -> list[AirconExtra]:
    """Return the appliance's extras catalog: aircon for ACs, floor_heater for FHs."""
    if appliance.type == APPLIANCE_TYPE_FLOOR_HEATER:
        return appliance.floor_heater.extras if appliance.floor_heater else []
    if appliance.type == APPLIANCE_TYPE_AC:
        return appliance.aircon.extras if appliance.aircon else []
    return []


def extra_platform(extra: AirconExtra) -> Platform | None:
    """Return the platform owning this extra, or None when nothing can render it.

    The single classification shared by the three extras platforms: a
    binary on/off "choice" is a switch, any other choice offering options
    is a select, and a "time" extra is a time entity. An unknown type — or
    a choice with an empty options list, which has nothing to select from —
    gets no entity at all. Availability is deliberately NOT considered: the
    catalog is static across operation modes and only each entry's
    availability flips with the current mode (probe-verified), so every
    supported extra gets an entity whose ``available`` tracks the flips.
    """
    if extra.type == EXTRA_TYPE_TIME:
        return Platform.TIME
    if extra.type != EXTRA_TYPE_CHOICE:
        return None
    values = {option.value for option in extra.options}
    if values == EXTRA_ON_OFF:
        return Platform.SWITCH
    return Platform.SELECT if values else None


class NatureRemoExtraEntity(NatureRemoApplianceEntity):
    """Base for entities backed by one remote-side extra parameter.

    Extras (e.g. Daikin autoclean/humid/new_sleep, Corona save_energy) are
    remote-side state baked into every transmitted frame; writes send only
    the current power button plus the merged extras so nothing else
    changes. ACs write through aircon_settings; floor heaters through
    floor_heater_settings. Shared by the switch (binary choice), select
    (multi-option choice), and time (type "time") platforms.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: NatureRemoCoordinator,
        appliance_id: str,
        extra: AirconExtra,
    ) -> None:
        """Initialize from the appliance's extras catalog entry."""
        super().__init__(coordinator, appliance_id)
        self._extra_id = extra.id
        self._attr_unique_id = f"{appliance_id}_extra_{extra.id}"

    @property
    def available(self) -> bool:
        """Track the extra's mode-dependent catalog availability.

        The extras catalog is static across operation modes, but each entry's
        ``availability`` flips between "available" and "hidden" with the
        CURRENT mode (probe-verified on a Daikin arc472a82: e.g. powerful is
        available in warm/cool but hidden in dry/blow/auto). Writing a hidden
        extra returns HTTP 200 yet is silently ignored server-side, so the
        entity must go unavailable instead of becoming a silent no-op.
        """
        if not super().available:
            return False
        return any(
            extra.id == self._extra_id and extra.availability == EXTRA_AVAILABLE
            for extra in extras_catalog(self.appliance)
        )

    @property
    def _stored_value(self) -> str | None:
        """The extra's stored value, if the API reports one."""
        settings = self.appliance.settings
        if settings is None:
            return None
        return settings.extra.get(self._extra_id)

    async def _async_write_extra(self, value: str) -> None:
        """Write the extra value, preserving the current power button."""
        async with self.coordinator.async_write_lock(self._appliance_id):
            # Read the appliance only under the lock: every settings payload
            # embeds the full extras dict (omitted extras are cleared
            # server-side), so a write that just finished on another platform
            # must be merged in here instead of being silently reverted.
            appliance = self.coordinator.data.appliances.get(self._appliance_id)
            if appliance is None:
                raise HomeAssistantError(
                    f"Failed to update {self.appliance.nickname}: the appliance "
                    "is no longer reported by the Nature API"
                )
            settings = appliance.settings
            new_extra = dict(settings.extra) if settings is not None else {}
            new_extra[self._extra_id] = value
            button = settings.button if settings is not None else None
            try:
                if appliance.type == APPLIANCE_TYPE_FLOOR_HEATER:
                    # floor_heater_settings returns the FULL updated Appliance,
                    # so the fresh extras catalog replaces the old one wholesale.
                    new_appliance = (
                        await self.coordinator.client.set_floor_heater_settings(
                            appliance.id, button=button, extra=new_extra
                        )
                    )
                else:
                    new_settings = await self.coordinator.client.set_aircon_settings(
                        appliance.id, button=button, extra=new_extra
                    )
                    new_appliance = replace(appliance, settings=new_settings)
            except NatureRemoError as err:
                raise HomeAssistantError(
                    command_error_message(f"Failed to update {appliance.nickname}", err)
                ) from err
            # Apply server truth first so entity state never lies, then verify
            # the echo: a successful write always echoes the extra back
            # (probe-verified), while a write the server silently ignored (the
            # extra went hidden between polls, e.g. right after a mode change)
            # returns 200 with the extra missing from settings.extra.
            self.coordinator.async_update_appliance(new_appliance)
            echoed = (
                new_appliance.settings.extra.get(self._extra_id)
                if new_appliance.settings is not None
                else None
            )
            if echoed != value:
                raise HomeAssistantError(
                    f"Failed to update {appliance.nickname}: the API ignored the "
                    f"write to '{self._extra_id}' (not available in the current "
                    "operation mode)"
                )
