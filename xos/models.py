
# Copyright 2017-present Open Networking Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from core.models import AddressPool
import os
from django.db.models import *
from xos.exceptions import *
from models_decl import *

def ip_to_mac(ip):
    (a, b, c, d) = ip.split('.')
    return "02:42:%02x:%02x:%02x:%02x" % (int(a), int(b), int(c), int(d))

class AddressManagerService (AddressManagerService_decl):
    class Meta:
        proxy = True


    def get_gateways(self):
        gateways = []
        aps = self.addresspools.all()
        for ap in aps:
            gateways.append({"gateway_ip": ap.gateway_ip, "gateway_mac": ap.gateway_mac})

        return gateways

    def get_address_pool(self, name):
        ap = AddressPool.objects.filter(name=name, service=self)
        if not ap:
            raise Exception("Address Manager unable to find addresspool %s" % name)
        return ap[0]

    # TODO remove me once the old TOSCA engine is gone
    def get_service_instance(self, **kwargs):
        address_pool_name = kwargs.pop("address_pool_name")

        ap = self.get_address_pool(address_pool_name)

        # ip = ap.get_address()
        # if not ip:
        #     raise Exception("AddressPool '%s' has run out of addresses." % ap.name)

        t = AddressManagerServiceInstance(owner=self, **kwargs)
        # NOTE this will be added updated on save
        # t.public_ip = ip
        # t.public_mac = ip_to_mac(ip)
        t.address_pool_id = ap.id
        t.save()

        return t

class AddressManagerServiceInstance (AddressManagerServiceInstance_decl):

    class Meta:
        proxy = True

    @property
    def gateway_ip(self):
        if not self.address_pool:
            return None
        return self.address_pool.gateway_ip

    @property
    def gateway_mac(self):
        if not self.address_pool:
            return None
        return self.address_pool.gateway_mac

    @property
    def cidr(self):
        if not self.address_pool:
            return None
        return self.address_pool.cidr

    @property
    def netbits(self):
        # return number of bits in the network portion of the cidr
        if self.cidr:
            parts = self.cidr.split("/")
            if len(parts) == 2:
                return int(parts[1].strip())
        return None

    def cleanup_addresspool(self):
        if self.address_pool:
            ap = self.address_pool
            if ap:
                ap.put_address(self.public_ip)
                self.public_ip = None

    def delete(self, *args, **kwargs):
        self.cleanup_addresspool()
        super(AddressManagerServiceInstance, self).delete(*args, **kwargs)

    def save(self, *args, **kwds):
        """
        We need to get an ip from addresspool when we create this model
        """
        if not self.id and not self.public_ip:
            self.public_ip = self.address_pool.get_address()
            self.public_mac = ip_to_mac(self.public_ip)
        super(AddressManagerServiceInstance, self).save(*args, **kwds)