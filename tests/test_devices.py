"""The microphone list comes from what Windows reports, which is messy: the same
device once per audio API, names truncated to 31 characters by MME, entries that
are not microphones, and a kernel-streaming view that refuses to open. These tests
feed that exact shape in.
"""

import sys

from stt.audio import devices

MME, DSOUND, WASAPI, WDMKS = 0, 1, 2, 3
APIS = [
    {"name": "MME", "default_input_device": 1},              # truncated name
    {"name": "Windows DirectSound", "default_input_device": 4},
    {"name": "Windows WASAPI", "default_input_device": 6},   # full name: the default
    {"name": "Windows WDM-KS", "default_input_device": 8},
]


def _dev(name, api, ch=2):
    return {"name": name, "max_input_channels": ch, "hostapi": api}


# The shape Windows reports: a USB headset (the default), the laptop array, a
# disconnected bluetooth headset only the kernel driver knows about, and the API
# mappers. The two headsets share their first 31 characters on purpose — that is
# where MME cuts names, and telling them apart is the point of several tests.
DEVICES = [
    _dev("Asignador de sonido Microsoft - Input", MME),
    _dev("Microphone of the headset with ", MME),             # truncated at 31
    _dev("Microphone Array (Realtek(R) Au", MME, ch=4),       # truncated at 31
    _dev("Controlador primario de captura de sonido", DSOUND),
    _dev("Microphone of the headset with mic (Studio 7.1 USB)", DSOUND),
    _dev("Microphone Array (Realtek(R) Audio)", DSOUND, ch=4),
    _dev("Microphone of the headset with mic (Studio 7.1 USB)", WASAPI),
    _dev("Input (Generic Bluetooth Speaker)", WDMKS),
    _dev("Microphone of the headset with mic (Generic Bluetooth Audio)",
         WDMKS, ch=1),
    {"name": "Speakers (Realtek)", "max_input_channels": 0, "hostapi": DSOUND},
]


class FakeSD:
    def __init__(self, device_list=DEVICES, apis=APIS, default_index=1):
        self._devices = device_list
        self._apis = apis
        self.default = type("D", (), {"device": [default_index, 5]})()

    def query_devices(self):
        return self._devices

    def query_hostapis(self):
        return self._apis


def _install(monkeypatch, fake=None):
    monkeypatch.setitem(sys.modules, "sounddevice", fake or FakeSD())


class TestListInputDevices:
    def test_drops_what_is_not_a_microphone(self, monkeypatch):
        _install(monkeypatch)
        names = [d.name for d in devices.list_input_devices()]
        assert not any("Asignador" in n or "Controlador primario" in n for n in names)
        assert "Input (Generic Bluetooth Speaker)" not in names
        assert "Speakers (Realtek)" not in names          # no input channels

    def test_keeps_the_full_name_of_a_truncated_duplicate(self, monkeypatch):
        _install(monkeypatch)
        names = [d.name for d in devices.list_input_devices()]
        assert "Microphone Array (Realtek(R) Audio)" in names
        assert "Microphone Array (Realtek(R) Au" not in names

    def test_hides_devices_only_the_kernel_driver_offers(self, monkeypatch):
        """WDM-KS wants exclusive access, so those entries fail to open."""
        _install(monkeypatch)
        names = [d.name for d in devices.list_input_devices()]
        assert not any("Generic Bluetooth" in n for n in names)

    def test_kernel_devices_are_the_fallback_when_alone(self, monkeypatch):
        _install(monkeypatch, FakeSD([_dev("Only KS mic", WDMKS)], APIS, 0))
        assert [d.name for d in devices.list_input_devices()] == ["Only KS mic"]

    def test_default_comes_from_wasapi_and_is_first(self, monkeypatch):
        """MME's truncated name is ambiguous, so the default is read from WASAPI."""
        _install(monkeypatch, FakeSD(DEVICES, APIS, default_index=1))
        result = devices.list_input_devices()
        assert result[0].is_default
        assert result[0].name.endswith("(Studio 7.1 USB)")
        assert sum(d.is_default for d in result) == 1

    def test_no_audio_backend(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "sounddevice", None)
        assert devices.list_input_devices() == []


class TestResolveInputDevice:
    def test_auto_means_let_windows_choose(self, monkeypatch):
        _install(monkeypatch)
        assert devices.resolve_input_device("auto") is None
        assert devices.resolve_input_device("") is None

    def test_an_index_passes_through(self, monkeypatch):
        _install(monkeypatch)
        assert devices.resolve_input_device("7") == 7

    def test_resolves_to_a_single_index(self, monkeypatch):
        """The bug this exists for: sounddevice raises when a name matches several."""
        _install(monkeypatch)
        index = devices.resolve_input_device(
            "Microphone of the headset with mic (Studio 7.1 USB)")
        assert index in (4, 6)              # the DirectSound or WASAPI entry
        assert isinstance(index, int)

    def test_prefers_the_earlier_api(self, monkeypatch):
        """Both DirectSound and WASAPI list it; DirectSound is preferred."""
        _install(monkeypatch)
        assert devices.resolve_input_device(
            "Microphone of the headset with mic (Studio 7.1 USB)") == 4

    def test_a_fragment_matches(self, monkeypatch):
        _install(monkeypatch)
        assert devices.resolve_input_device("Microphone Array") == 2   # MME comes first

    def test_exact_match_beats_a_shared_prefix(self, monkeypatch):
        """The bluetooth headset must not resolve to the USB one just because MME cut
        the name where the two happen to agree."""
        _install(monkeypatch)
        index = devices.resolve_input_device(
            "Microphone of the headset with mic (Generic Bluetooth Audio)")
        assert index == 8                   # the bluetooth entry, not the USB one at 1

    def test_unknown_name_falls_back_to_the_default(self, monkeypatch):
        _install(monkeypatch)
        assert devices.resolve_input_device("Ghost microphone") is None


class TestDescribeCurrent:
    def test_configured_name_is_returned_as_is(self):
        assert devices.describe_current("Microphone Array") == "Microphone Array"

    def test_auto_names_the_windows_default(self, monkeypatch):
        _install(monkeypatch)
        assert "Studio 7.1 USB" in devices.describe_current("auto")
