from enum import Enum

import logging
import can

from gateway import datapoint
from gateway.exceptions import NoValidMessageException
from gateway.datatypes import Unsigned, Signed, List, String


class Operation(Enum):
    """Operations in CAN-Message"""
    RESPONSE = 0x42
    GET_REQUEST = 0x40
    SET_REQUEST = 0x46

    @staticmethod
    def list():
        return list(map(lambda c: c.value, Operation))


class Message:
    """Message - Basic Class for all Messages"""

    def __init__(self, arbitration_id, operation_id):
        self.arbitration_id = arbitration_id
        self.message_id = arbitration_id >> 24
        self.priority = (arbitration_id >> 16) & 0xff
        self.device_type = (arbitration_id >> 8) & 0xff
        self.device_id = arbitration_id & 0xff
        self.operation_id = operation_id
        self.data = bytearray()

    def _is_valid(self):
        return self.operation_id in Operation.list()


class ReceiveMessage(Message):
    def __init__(self, arbitration_id, operation_id, message_len):
        super().__init__(arbitration_id, operation_id)
        self.nb_remaining = message_len + 1
        self.message_len = message_len

    def put_data(self, data):
        if not self._is_valid():
            return
        self.data.extend(data)
        self.nb_remaining -= 1

    def put_extended_data(self, data):
        if not self._is_valid():
            return
        self.data.extend(data[:-2])
        self.nb_remaining -= 1

    def parse(self):
        if len(self.data) < 6:
            raise NoValidMessageException("Message too short for parsing")
        function_group = self.data[2]
        function_number = self.data[3]
        datapoint_id = int.from_bytes(self.data[4:6], byteorder='big', signed=False)
        datapoint_value = self.data[6:]
        # Ab hier gibts evtl ein traced end weil kein bekanntes datum

        if len(datapoint_value) == 1:
          v1=Signed(8, 1).convert_from_bytes(datapoint_value)
          v2=Unsigned(8, 1).convert_from_bytes(datapoint_value)
          v3=List().convert_from_bytes(datapoint_value)
          #try:
          #  v4=String().convert_from_bytes(datapoint_value)
          #except UniDecodeError as e:
          #  v4="NOSTRING"
          datapoints=[v1,v2,v3]
        elif len(datapoint_value) == 2:
          v1=Signed(16, 1).convert_from_bytes(datapoint_value)
          v2=Unsigned(16, 1).convert_from_bytes(datapoint_value)
          v3=List().convert_from_bytes(datapoint_value)
          #try:
          #  v4=String().convert_from_bytes(datapoint_value)
          #except UniDecodeError as e:
          #  v4="NOSTRING"
          datapoints=[v1,v2,v3]
        elif len(datapoint_value) == 4:
          v1=Signed(32, 1).convert_from_bytes(datapoint_value)
          v2=Unsigned(32, 1).convert_from_bytes(datapoint_value)
          v3=List().convert_from_bytes(datapoint_value)
          #try:
          #  v4=String().convert_from_bytes(datapoint_value)
          #except UniDecodeError as e:
          #  v4="NOSTRING"
          datapoints=[v1,v2,v3]
        else:
          v3=List().convert_from_bytes(datapoint_value)
          #try:
          #  v4=String().convert_from_bytes(datapoint_value)
          #except UniDecodeError as e:
          #  v4="NOSTRING"
          datapoints=[v3]

        logging.debug(f"FLO: FG: {function_group:2} FN: {function_number:2} ID: {datapoint_id:5} V: ({datapoints}) ORIG: {datapoint_value} LEN:{len(datapoint_value)}")
        read_datapoint = datapoint.get_datapoint_by_id(function_group, function_number, datapoint_id)
        datapoint_limits = read_datapoint.get_datapoint_limits()
        converted_value = read_datapoint.get_datapoint_type().convert_from_bytes(self.data[6:])
        if datapoint_limits and "lower" in datapoint_limits.keys() and "upper" in datapoint_limits.keys():
            if converted_value < datapoint_limits["lower"] or \
                converted_value > datapoint_limits["upper"]:
                raise NoValidMessageException(f"Message with Value {converted_value} is out of bounds of limits {datapoint_limits}")

        return read_datapoint, Operation(self.operation_id), converted_value

    def __str__(self):
        return "Receive Message: id: {}, priority: {}, operation: {}, nb_remaining: {}, message_len: {}, " \
               "device_type: {}, device_id: {}, data: {}".format(self.message_id, self.priority,
                                                                 Operation(self.operation_id), self.nb_remaining,
                                                                 self.message_len, self.device_type, self.device_id,
                                                                 self.data[6:])


class SendMessage(Message):
    _message_size = 8

    def __init__(self, arbitration_id, operation_id, datapoint_of_message):
        super().__init__(arbitration_id, operation_id)
        self.message_len = 1
        self.header_data = bytearray()
        self._put_header(datapoint_of_message)

    def _put_header(self, datapoint_of_message):
        self.header_data.append(self.message_len)
        self.header_data.append(self.operation_id)
        self.header_data.append(datapoint_of_message.function_group)
        self.header_data.append(datapoint_of_message.function_number)
        self.header_data.extend(datapoint_of_message.get_datapoint_by_bytes())

    def put_data(self, data):
        if not self._is_valid():
            return
        self.data.extend(data)

    def put_single_data(self, data):
        self.put_data([data])

    def to_can_message(self):
        can_data = bytearray()
        can_data.extend(self.header_data)
        can_data.extend(self.data)

        # todo: split into more can messages if too long
        if len(self.data) + len(self.header_data) > self._message_size:
            raise NoValidMessageException("Message is too long")

        return can.Message(arbitration_id=self.arbitration_id, data=can_data, is_extended_id=True)

    def __str__(self):
        return "Send Message: id: {}, priority: {}, operation: {}, message_len: {}, device_type: {}, device_id: {}, " \
               "data: {}".format(self.message_id, self.priority, Operation(self.operation_id), self.message_len,
                                 self.device_type, self.device_id, self.data)


def get_message_id(arbitration_id):
    return arbitration_id >> 24


def get_message_priority(arbitration_id):
    return arbitration_id >> 16 & 0xff


def get_message_device_type(arbitration_id):
    return arbitration_id >> 8 & 0xfff


def get_message_device_id(arbitration_id):
    return arbitration_id & 0xff


def get_message_header(data):
    return data[0]


def get_message_len(data):
    return data[0] >> 3


def get_operation_id(data):
    return data[1]


def build_arbitration_id(message_id, priority, device_type, device_id):
    return (message_id << 24) | (priority << 16) | (device_type << 8) | device_id
