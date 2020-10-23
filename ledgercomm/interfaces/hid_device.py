"""ledgercomm.interfaces.hid_device module."""

import logging
from typing import List, Tuple, Optional

try:
    import hid
except ImportError:
    hid = None

from ledgercomm.interfaces.comm import Comm


class HID(Comm):
    """HID class.

    Mainly used to communicate with Nano S/X through USB.

    Parameters
    ----------
    vendor_id: int
        Vendor ID of the device. Default to Ledger Vendor ID 0x2C97.

    Attributes
    ----------
    device : hid.device
        HID device connection.
    path : Optional[bytes]
        Path of the HID device.
    __opened : bool
        Whether the connection to the HID device is opened or not.

    """

    def __init__(self, vendor_id: int = 0x2C97) -> None:
        """Init constructor of HID."""
        if hid is None:
            raise ImportError("hidapi is not installed, try: "
                              "'pip install ledgercomm[hid]'")

        self.device = hid.device()
        self.path: Optional[bytes] = None
        self.__opened: bool = False
        self.vendor_id: int = vendor_id

    def open(self) -> None:
        """Open connection to the HID device.

        Returns
        -------
        None

        """
        if not self.__opened:
            self.path = HID.enumerate_devices(self.vendor_id)[0]
            self.device.open_path(self.path)
            self.device.set_nonblocking(True)
            self.__opened = True

    @staticmethod
    def enumerate_devices(vendor_id: int = 0x2C97) -> List[bytes]:
        """Enumerate HID devices to find Nano S/X.

        Parameters
        ----------
        vendor_id: int
            Vendor ID of the device. Default to Ledger Vendor ID 0x2C97.

        Returns
        -------
        List[bytes]
            List of paths to HID devices which should be Nano S or Nano X.

        """
        devices: List[bytes] = []

        for hid_device in hid.enumerate(vendor_id, 0):
            if (hid_device.get("interface_number") == 0 or
                    hid_device.get("usage_page") == 0xffa0):
                devices.append(hid_device["path"])

        assert len(devices) != 0, f"Can't find device with vendor_id {vendor_id}"

        return devices

    def send(self, data: bytes) -> int:
        """Send `data` through HID device `self.device`.

        Parameters
        ----------
        data : bytes
            Bytes with `data` to send.

        Returns
        -------
        int
            Total length of data sent to the device.

        """
        if not data:
            raise Exception("Can't send empty data!")

        data = int.to_bytes(len(data), 2, byteorder="big") + data
        offset: int = 0
        seq_idx: int = 0
        length: int = 0

        while offset < len(data):
            # Header: channel (0x101), tag (0x05), sequence index
            header: bytes = b"\x01\x01\x05" + seq_idx.to_bytes(2, byteorder="big")
            data_chunk: bytes = (header +
                                 data[offset:offset + 64 - len(header)])

            self.device.write(b"\x00" + data_chunk)
            length += len(data_chunk) + 1
            logging.debug("=> %s", data_chunk.hex())
            offset += 64 - len(header)
            seq_idx += 1

        return length

    def recv(self) -> Tuple[int, bytes]:
        """Receive data through HID device `self.device`.

        Blocking IO.

        Returns
        -------
        Tuple[int, bytes]
            A pair (sw, data) containing the status word and associated datas.

        """
        seq_idx: int = 0
        self.device.set_nonblocking(False)
        data_chunk: bytes = bytes(self.device.read(64 + 1))
        self.device.set_nonblocking(True)

        assert data_chunk[:2] == b"\x01\x01"
        assert data_chunk[2] == 5
        assert data_chunk[3:5] == seq_idx.to_bytes(2, byteorder="big")

        data_len: int = int.from_bytes(data_chunk[5:7], byteorder="big")
        data: bytes = data_chunk[7:]

        while len(data) < data_len:
            read_bytes = bytes(self.device.read(64 + 1, timeout_ms=1000))
            data += read_bytes[5:]

        sw: int = int.from_bytes(data[data_len - 2:data_len], byteorder="big")
        data = data[:data_len - 2]

        logging.debug("<= %s %s", data.hex(), hex(sw)[2:])

        return sw, data

    def exchange(self, data: bytes) -> Tuple[int, bytes]:
        """Exchange (send + receive) with `self.device`.

        Parameters
        ----------
        data : bytes
            Bytes with `data` to send.

        Returns
        -------
        Tuple[int, bytes]
            A pair (sw, data) containing the status word and associated datas.

        """
        self.send(data)

        return self.recv()  # blocking IO

    def close(self) -> None:
        """Close connection to HID device `self.device`.

        Returns
        -------
        None

        """
        if self.__opened:
            self.device.close()
            self.__opened = False