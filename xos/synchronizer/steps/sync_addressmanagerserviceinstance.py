
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

import requests
from synchronizers.new_base.syncstep import SyncStep, DeferredException
from synchronizers.new_base.modelaccessor import *

from xosconfig import Config
from multistructlog import create_logger

log = create_logger(Config().get('logging'))

DATAPLANE_IP = "dataPlaneIp"
PREFIX = "prefix"
NEXT_HOP = "nextHop"

class SyncAddressManagerServiceInstance(SyncStep):
    provides=[AddressManagerServiceInstance]
    observes = AddressManagerServiceInstance
    requested_interval=30
       
    def get_fabric_onos_service_internal(self):
        # There will be a ServiceInstanceLink from the FabricService to the Fabric ONOS App
        fs = FabricService.objects.first()
        for link in fs.subscribed_links.all():
            if link.provider_service_instance:
                # cast from ServiceInstance to ONOSApp
                service_instance = link.provider_service_instance.leaf_model
                # cast from Service to ONOSService
                return service_instance.owner.leaf_model

        return None

    def get_fabric_onos_service(self):
        fos = self.get_fabric_onos_service_internal()
        if not fos:
            raise Exception("Fabric ONOS service not found")
        return fos

    def get_node_tag(self, node, tagname):
        tags = Tag.objects.filter(content_type=model_accessor.get_content_type_id(node),
                                  object_id=node.id,
                                  name=tagname)
        if tags:
            return tags[0].value
        else:
            return None

    def fetch_pending(self, deleted):
        # If fetch_pending is being called for delete, then just execute the standard delete logic.
        if deleted:
            return super(SyncAddressManagerServiceInstance, self).fetch_pending(deleted)

        fs = FabricService.objects.first()
        if (not fs) or (not fs.autoconfig):
            log.info("Not FabricServer or not autoconfig. Returning []");
            return []

        objs = super(SyncAddressManagerServiceInstance, self).fetch_pending(deleted)
        objs = list(objs)

        # Check that each is a valid VSG tenant or instance
        for address_si in objs[:]:
            sub = self.get_subscriber(address_si)
            if sub:
                # TODO: This check is making assumptions about the subscriber service. Consider breaking hardcoded
                # dependency.
                if (not hasattr(sub, "instance")) or (not sub.instance):
                    log.info("Skipping %s because it has no instance" % address_si)
                    objs.remove(address_si)
            else:
                # Maybe the Address is for an instance
                # TODO: tenant_for_instance_id needs to be a real database field
                instance_id = address_si.get_attribute("tenant_for_instance_id")
                if not instance_id:
                    log.info("Skipping %s because it has no tenant_for_instance_id" % address_si)
                    objs.remove(address_si)
                else:
                    instances = Instance.objects.filter(id=instance_id)
                    if not instances:
                        log.error("Skipping %s because it appears to be linked to a dead instance" % address_si)
                        objs.remove(address_si)
                    elif not instances[0].instance_name:
                        log.info("Skipping %s because it has no instance.instance_name" % address_si)
                        objs.remove(address_si)

        return objs

    def get_subscriber(self, address_si):
        links = address_si.provided_links.all()
        for link in links:
            if not link.subscriber_service_instance:
                continue
            # cast from ServiceInstance to VSGTEnant or similar
            sub = link.subscriber_service_instance.leaf_model
            # TODO: check here to make sure it's an appropriate type of ServiceInstance ?
            return sub
        return None

    def get_routes_url(self, fos):
        url = 'http://%s:%s/onos/routeservice/routes' % (fos.rest_hostname, fos.rest_port)

        log.info("url: %s" % url)
        return url

    def sync_record(self, address_si):
        fos = self.get_fabric_onos_service()

        data = self.map_tenant_to_route(address_si)
        if not data:
            # Raise an exception so the synchronizer does not mark this record as synced
            raise Exception("map_tenant_to_route returned no data for %s" % address_si)

        r = self.post_route(fos, data)

        log.info("Posted %s: status: %s result '%s'" % (address_si, r.status_code, r.text))

    def delete_record(self, address_si):
        pass
        # Disabled for now due to lack of feedback state field
        # self.delete_route(self.get_fabric_onos_service(),  self.map_tenant_to_route(address_si))


    def map_tenant_to_route(self, address_si):
        instance = None
        # Address setup is kind of hacky right now, we'll
        # need to revisit.  The idea is:
        # * Look up the instance corresponding to the address
        # * Look up the node running the instance
        # * Get the "dataPlaneIp" tag, push to the fabric

        sub = self.get_subscriber(address_si)
        if sub:
            # TODO: This check is making assumptions about the subscriber service. Consider breaking hardcoded
            # dependency.
            if hasattr(sub, "instance"):
                instance = sub.instance
        else:
            instance_id = address_si.get_attribute("tenant_for_instance_id")
            instances = Instance.objects.filter(id=instance_id)
            if instances:
                instance = instances[0]

        if not instance:
            return None

        node = instance.node
        dataPlaneIp = node.dataPlaneIp

        if not dataPlaneIp:
            raise DeferredException("No IP found for node %s tenant %s -- skipping" % (str(node), str(address_si)))

        data = {
            PREFIX : "%s/32" % address_si.public_ip,
            NEXT_HOP : dataPlaneIp.split('/')[0]
        }

        return data

    def delete_route(self, fos, route):
        url = self.get_routes_url(fos)

        r = requests.delete(url, json=route, auth=(fos.rest_username, fos.rest_password))

        log.info("status: %s" % r.status_code)
        log.info('result: %s' % r.text)

        return r

    def post_route(self, fos, route):
        url = self.get_routes_url(fos)
        return requests.post(url, json=route, auth=(fos.rest_username, fos.rest_password))

