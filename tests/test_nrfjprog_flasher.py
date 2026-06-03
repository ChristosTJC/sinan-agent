from agent.tools.nrfjprog_flasher import NrfjprogFlasher, detect_family_from_chip


def test_detect_family_from_nrf_chip():
    assert detect_family_from_chip("nRF52840") == "NRF52"
    assert detect_family_from_chip("nRF5340") == "NRF53"


def test_generate_flash_args_for_nrf52840():
    flasher = NrfjprogFlasher()

    args = flasher.generate_flash_args("build/zephyr/zephyr.hex", "nRF52840")

    assert args == [
        "nrfjprog",
        "--program",
        "build/zephyr/zephyr.hex",
        "--family",
        "NRF52",
        "--sectorerase",
        "--verify",
        "--reset",
    ]


def test_generate_flash_args_for_nrf5340_application_core():
    flasher = NrfjprogFlasher()

    args = flasher.generate_flash_args(
        "build/zephyr/zephyr.hex",
        "nRF5340",
        coprocessor="CP_APPLICATION",
    )

    assert "--family" in args
    assert "NRF53" in args
    assert "--coprocessor" in args
    assert "CP_APPLICATION" in args
