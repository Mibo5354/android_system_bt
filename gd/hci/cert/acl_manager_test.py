#!/usr/bin/env python3
#
#   Copyright 2020 - The Android Open Source Project
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import os
import sys
import logging

from cert.gd_base_test_facade_only import GdFacadeOnlyBaseTestClass
from cert.event_stream import EventStream
from cert.truth import assertThat
from google.protobuf import empty_pb2 as empty_proto
from hci.facade import acl_manager_facade_pb2 as acl_manager_facade
from neighbor.facade import facade_pb2 as neighbor_facade
from hci.facade import controller_facade_pb2 as controller_facade
from hci.facade import facade_pb2 as hci_facade
import bluetooth_packets_python3 as bt_packets
from bluetooth_packets_python3 import hci_packets
from captures import ReadBdAddrCompleteCapture
from captures import ConnectionCompleteCapture
from captures import ConnectionRequestCapture
from py_hci import PyHci
from py_acl_manager import PyAclManager


class AclManagerTest(GdFacadeOnlyBaseTestClass):

    def setup_class(self):
        super().setup_class(dut_module='HCI_INTERFACES', cert_module='HCI')

    def test_dut_connects(self):
        with PyHci(self.cert) as cert_hci, \
            PyAclManager(self.dut) as dut_acl_manager:

            cert_hci.enable_inquiry_and_page_scan()
            cert_address = cert_hci.read_own_address()

            with EventStream(
                    self.dut.hci_acl_manager.CreateConnection(
                        acl_manager_facade.ConnectionMsg(
                            address_type=int(
                                hci_packets.AddressType.PUBLIC_DEVICE_ADDRESS),
                            address=bytes(cert_address,
                                          'utf8')))) as connection_event_stream:

                cert_acl = cert_hci.accept_connection()
                cert_acl.send_first(
                    b'\x26\x00\x07\x00This is just SomeAclData from the Cert')

                # DUT gets a connection complete event and sends and receives
                connection_complete = ConnectionCompleteCapture()
                connection_event_stream.assert_event_occurs(connection_complete)
                dut_handle = connection_complete.get().GetConnectionHandle()

                self.dut.hci_acl_manager.SendAclData(
                    acl_manager_facade.AclData(
                        handle=dut_handle,
                        payload=bytes(
                            b'\x29\x00\x07\x00This is just SomeMoreAclData from the DUT'
                        )))

                assertThat(cert_hci.get_acl_stream()).emits(
                    lambda packet: b'SomeMoreAclData' in packet.data)
                assertThat(dut_acl_manager.get_acl_stream()).emits(
                    lambda packet: b'SomeAclData' in packet.payload)

    def test_cert_connects(self):
        with PyHci(self.cert) as cert_hci, \
            EventStream(self.dut.hci_acl_manager.FetchIncomingConnection(empty_proto.Empty())) as incoming_connection_stream, \
            EventStream(self.dut.hci_acl_manager.FetchAclData(empty_proto.Empty())) as acl_data_stream:

            # DUT Enables scans and gets its address
            dut_address = self.dut.hci_controller.GetMacAddressSimple()

            self.dut.neighbor.EnablePageScan(
                neighbor_facade.EnableMsg(enabled=True))

            cert_hci.initiate_connection(dut_address)

            # DUT gets a connection request
            connection_complete = ConnectionCompleteCapture()
            assertThat(incoming_connection_stream).emits(connection_complete)
            dut_handle = connection_complete.get().GetConnectionHandle()

            self.dut.hci_acl_manager.SendAclData(
                acl_manager_facade.AclData(
                    handle=dut_handle,
                    payload=bytes(
                        b'\x29\x00\x07\x00This is just SomeMoreAclData from the DUT'
                    )))

            cert_acl = cert_hci.complete_connection()
            cert_acl.send_first(
                b'\x26\x00\x07\x00This is just SomeAclData from the Cert')

            assertThat(cert_hci.get_acl_stream()).emits(
                lambda packet: b'SomeMoreAclData' in packet.data)
            assertThat(acl_data_stream).emits(
                lambda packet: b'SomeAclData' in packet.payload)

    def test_recombination_l2cap_packet(self):
        with PyHci(self.cert) as cert_hci, \
            PyAclManager(self.dut) as dut_acl_manager:

            # CERT Enables scans and gets its address
            cert_hci.enable_inquiry_and_page_scan()
            cert_address = cert_hci.read_own_address()

            with EventStream(
                    self.dut.hci_acl_manager.CreateConnection(
                        acl_manager_facade.ConnectionMsg(
                            address_type=int(
                                hci_packets.AddressType.PUBLIC_DEVICE_ADDRESS),
                            address=bytes(cert_address,
                                          'utf8')))) as connection_event_stream:

                cert_acl = cert_hci.accept_connection()
                cert_acl.send_first(b'\x06\x00\x07\x00Hello')
                cert_acl.send_continuing(b'!')
                cert_acl.send_first(b'\xe8\x03\x07\x00' + b'Hello' * 200)

                # DUT gets a connection complete event and sends and receives
                connection_complete = ConnectionCompleteCapture()
                connection_event_stream.assert_event_occurs(connection_complete)
                dut_handle = connection_complete.get().GetConnectionHandle()

                assertThat(dut_acl_manager.get_acl_stream()).emits(
                    lambda packet: b'Hello!' in packet.payload,
                    lambda packet: b'Hello' * 200 in packet.payload).inOrder()
