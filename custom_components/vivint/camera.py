"""Support for Vivint cameras."""
import logging

from vivintpy.devices.camera import Camera as VivintCamera

from homeassistant.components.camera import SUPPORT_STREAM, Camera
from homeassistant.components.ffmpeg import async_get_image

from .const import (
    CONF_HD_STREAM,
    CONF_RTSP_STREAM,
    CONF_RTSP_URL_LOGGING,
    DEFAULT_HD_STREAM,
    DEFAULT_RTSP_STREAM,
    DEFAULT_RTSP_URL_LOGGING,
    DOMAIN,
    RTSP_STREAM_DIRECT,
    RTSP_STREAM_EXTERNAL,
)
from .hub import VivintEntity, VivintHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Vivint cameras using config entry."""
    entities = []
    hub = hass.data[DOMAIN][config_entry.entry_id]

    hd_stream = config_entry.options.get(CONF_HD_STREAM, DEFAULT_HD_STREAM)
    rtsp_stream = config_entry.options.get(CONF_RTSP_STREAM, DEFAULT_RTSP_STREAM)
    rtsp_url_logging = config_entry.options.get(
        CONF_RTSP_URL_LOGGING, DEFAULT_RTSP_URL_LOGGING
    )

    for system in hub.account.systems:
        for alarm_panel in system.alarm_panels:
            for device in alarm_panel.devices:
                if type(device) is VivintCamera:
                    if rtsp_url_logging:
                        await log_rtsp_urls(device)

                    entities.append(
                        VivintCam(
                            device=device,
                            hub=hub,
                            hd_stream=hd_stream,
                            rtsp_stream=rtsp_stream,
                        )
                    )

    if not entities:
        return

    async_add_entities(entities, True)


async def log_rtsp_urls(device: VivintCamera):
    """Logs the rtsp urls of a Vivint camera."""
    _LOGGER.info(
        "%s rtsp urls:\n  direct hd: %s\n  direct sd: %s\n  internal hd: %s\n  internal sd: %s\n  external hd: %s\n  external sd: %s",
        device.name,
        await device.get_direct_rtsp_url(hd=True),
        await device.get_direct_rtsp_url(hd=False),
        await device.get_rtsp_url(internal=True, hd=True),
        await device.get_rtsp_url(internal=True, hd=False),
        await device.get_rtsp_url(internal=False, hd=True),
        await device.get_rtsp_url(internal=False, hd=False),
    )


class VivintCam(VivintEntity, Camera):
    """Vivint camera."""

    def __init__(
        self,
        device: VivintCamera,
        hub: VivintHub,
        hd_stream: bool = DEFAULT_HD_STREAM,
        rtsp_stream: int = DEFAULT_RTSP_STREAM,
    ):
        super().__init__(device=device, hub=hub)
        Camera.__init__(self)

        self.__hd_stream = hd_stream
        self.__rtsp_stream = rtsp_stream
        self.__stream_source = None
        self.__last_image = None

    @property
    def supported_features(self):
        """Return supported features for this camera."""
        return SUPPORT_STREAM

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"{self.device.alarm_panel.id}-{self.device.id}"

    async def stream_source(self):
        """Return the source of the stream."""
        if not self.__stream_source:
            self.__stream_source = (
                await self.device.get_direct_rtsp_url(hd=self.__hd_stream)
                if self.__rtsp_stream == RTSP_STREAM_DIRECT
                else None
            ) or await self.device.get_rtsp_url(
                internal=self.__rtsp_stream != RTSP_STREAM_EXTERNAL, hd=self.__hd_stream
            )
        return self.__stream_source

    async def async_camera_image(self):
        """Return a frame from the camera stream."""
        try:
            self.__last_image = await async_get_image(
                self.hass, await self.stream_source()
            )
        except:
            _LOGGER.debug(f"Could not retrieve latest image for {self.name}")
        finally:
            return self.__last_image
