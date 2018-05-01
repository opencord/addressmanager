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

import functools
import unittest
from mock import patch, call, Mock, PropertyMock
import requests_mock

import os, sys

# Hack to load synchronizer framework
test_path=os.path.abspath(os.path.dirname(os.path.realpath(__file__)))
xos_dir=os.path.join(test_path, "../../..")
if not os.path.exists(os.path.join(test_path, "new_base")):
    xos_dir=os.path.join(test_path, "../../../../../../orchestration/xos/xos")
    services_dir = os.path.join(xos_dir, "../../xos_services")
# END Hack to load synchronizer framework

def match_json(desired, req):
    if desired!=req.json():
        print >> sys.stderr, "mismatch: '%s' != '%s'" % (desired, req.json())
        return False
    return True

# generate model from xproto
def get_models_fn(service_name, xproto_name):
    name = os.path.join(service_name, "xos", xproto_name)
    if os.path.exists(os.path.join(services_dir, name)):
        return name
    else:
        name = os.path.join(service_name, "xos", "synchronizer", "models", xproto_name)
        if os.path.exists(os.path.join(services_dir, name)):
            return name
    raise Exception("Unable to find service=%s xproto=%s" % (service_name, xproto_name))
# END generate model from xproto

class TestSyncAddressManagerServiceInstance(unittest.TestCase):

    def setUp(self):
        global MockObjectList, model_accessor, SyncStep

        self.sys_path_save = sys.path
        sys.path.append(xos_dir)
        sys.path.append(os.path.join(xos_dir, 'synchronizers', 'new_base'))

        # Setting up the config module
        from xosconfig import Config
        config = os.path.join(test_path, "test_config.yaml")
        Config.clear()
        Config.init(config, "synchronizer-config-schema.yaml")
        # END Setting up the config module

        from synchronizers.new_base.mock_modelaccessor_build import build_mock_modelaccessor
        build_mock_modelaccessor(xos_dir, services_dir, [get_models_fn("fabric", "fabric.xproto"),
                                                         get_models_fn("addressmanager", "addressmanager.xproto"),
                                                         get_models_fn("onos-service", "onos.xproto")])
        import synchronizers.new_base.modelaccessor
        from synchronizers.new_base.syncstep import SyncStep
        from sync_addressmanagerserviceinstance import SyncAddressManagerServiceInstance, model_accessor

        from mock_modelaccessor import MockObjectList

        self.sync_step = SyncAddressManagerServiceInstance()

        # import all class names to globals
        for (k, v) in model_accessor.all_model_classes.items():
            globals()[k] = v

        # Some of the functions we call have side-effects. For example, creating a VSGServiceInstance may lead to creation of
        # tags. Ideally, this wouldn't happen, but it does. So make sure we reset the world.
        model_accessor.reset_all_object_stores()

        # TODO: this should be addressed in the mock model accessor
        model_accessor.get_content_type_id = lambda x: x.self_content_type_id

        AddressManagerServiceInstance.get_attribute = None

        self.service = FabricService()
        self.onos_service = ONOSService(rest_hostname = "fabric_host", rest_port=1234)
        self.onos_app = ONOSApp(owner = self.onos_service)

        self.onos_dependency = ServiceDependency(subscriber_service = self.service,
                                                 provider_service_instance = self.onos_app)
        self.onos_service.provideded_links = MockObjectList(initial = [self.onos_dependency])
        self.service.subscribed_links = MockObjectList(initial = [self.onos_dependency])

        self.amsi_service_instance = AddressManagerServiceInstance(public_ip = "1.2.3.4",
                                                       public_mac="11:22:33:44:55:66",
                                                       provided_links = MockObjectList())
        self.amsi_inst = AddressManagerServiceInstance(public_ip = "5.6.7.8",
                                                       public_mac="55:66:77:88:99:00",
                                                       provided_links = MockObjectList())

    def tearDown(self):
        sys.path = self.sys_path_save

    def test_get_fabric_onos_service_internal(self):
        with patch.object(FabricService.objects, "get_items") as fabricservice_objects:
            fabricservice_objects.return_value =[self.service]

            osi = self.sync_step.get_fabric_onos_service_internal()
            self.assertEqual(osi, self.onos_service)

    def test_get_fabric_onos_service_internal_nolinks(self):
        with patch.object(FabricService.objects, "get_items") as fabricservice_objects:
            fabricservice_objects.return_value =[self.service]

            self.service.subscribed_links = MockObjectList(initial=[])

            osi = self.sync_step.get_fabric_onos_service_internal()
            self.assertEqual(osi, None)

    def test_get_fabric_onos_service(self):
        with patch.object(FabricService.objects, "get_items") as fabricservice_objects:
            fabricservice_objects.return_value =[self.service]

            osi = self.sync_step.get_fabric_onos_service()
            self.assertEqual(osi, self.onos_service)

    def test_get_fabric_onos_service_nolinks(self):
        with patch.object(FabricService.objects, "get_items") as fabricservice_objects:
            fabricservice_objects.return_value =[self.service]

            self.service.subscribed_links = MockObjectList(initial=[])

            with self.assertRaises(Exception) as e:
                osi = self.sync_step.get_fabric_onos_service()

            self.assertEqual(e.exception.message, "Fabric ONOS service not found")

    def test_get_node_tag(self):
        with patch.object(Tag.objects, "get_items") as tag_objects:
            node = Node(id=6745)
            tag = Tag(content_type = model_accessor.get_content_type_id(node),
                      object_id = node.id,
                      name="foo",
                      value="bar")
            tag_objects.return_value = [tag]

            self.assertEqual(self.sync_step.get_node_tag(node, "foo"), "bar")

    def test_fetch_pending(self):
        with patch.object(FabricService.objects, "get_items") as fabricservice_objects, \
                patch.object(AddressManagerServiceInstance, "get_attribute") as get_attribute, \
                patch.object(Instance.objects, "get_items") as instance_objects, \
                patch.object(SyncStep, "fetch_pending") as syncstep_fetch_pending:
            fabricservice_objects.return_value =[self.service]

            node = Node(dataPlaneIp = "11.22.33.44")
            instance1 = Instance(id=3445, node=node, instance_name="instance1")
            instance2 = Instance(id=3446, node=node, instance_name="instance2")
            instance_objects.return_value = [instance1, instance2]

            # for self.amsi_inst...
            get_attribute.return_value = instance1.id

            # for self.amsi_service_instance...
            some_service_instance = ServiceInstance(instance=instance2)
            some_link = ServiceInstanceLink(subscriber_service_instance=some_service_instance, provider_service_instance=self.amsi_service_instance)
            some_service_instance.subscribed_links = MockObjectList(initial=[some_link])
            self.amsi_service_instance.provided_links = MockObjectList(initial=[some_link])

            syncstep_fetch_pending.return_value = [self.amsi_inst, self.amsi_service_instance]

            objs = self.sync_step.fetch_pending(deleted = False)
            self.assertEqual(len(objs), 2)

    def test_fetch_pending_no_attribute(self):
        with patch.object(FabricService.objects, "get_items") as fabricservice_objects, \
                patch.object(AddressManagerServiceInstance, "get_attribute") as get_attribute, \
                patch.object(Instance.objects, "get_items") as instance_objects, \
                patch.object(SyncStep, "fetch_pending") as syncstep_fetch_pending:
            fabricservice_objects.return_value = [self.service]
            syncstep_fetch_pending.return_value = [self.amsi_inst, self.amsi_service_instance]

            node = Node(dataPlaneIp="11.22.33.44")
            instance2 = Instance(id=3446, node=node, instance_name="instance1")
            instance_objects.return_value = [instance2]

            # for self.amsi_inst, see that it has no instance
            get_attribute.return_value = None

            # for self.amsi_service_instance...
            some_service_instance = ServiceInstance(instance=instance2)
            some_link = ServiceInstanceLink(subscriber_service_instance=some_service_instance,
                                            provider_service_instance=self.amsi_service_instance)
            some_service_instance.subscribed_links = MockObjectList(initial=[some_link])
            self.amsi_service_instance.provided_links = MockObjectList(initial=[some_link])

            objs = self.sync_step.fetch_pending(deleted=False)

            self.assertEqual(len(objs), 1)

    def test_fetch_pending_no_subscriber_instance(self):
        with patch.object(FabricService.objects, "get_items") as fabricservice_objects, \
                patch.object(AddressManagerServiceInstance, "get_attribute") as get_attribute, \
                patch.object(Instance.objects, "get_items") as instance_objects, \
                patch.object(SyncStep, "fetch_pending") as syncstep_fetch_pending:
            fabricservice_objects.return_value =[self.service]

            node = Node(dataPlaneIp = "11.22.33.44")
            instance1 = Instance(id=3445, node=node, instance_name="instance1")
            instance_objects.return_value = [instance1]

            # for self.amsi_inst...
            get_attribute.return_value = instance1.id

            # for self.amsi_service_instance...
            some_service_instance = ServiceInstance(instance=None)
            some_link = ServiceInstanceLink(subscriber_service_instance=some_service_instance, provider_service_instance=self.amsi_service_instance)
            some_service_instance.subscribed_links = MockObjectList(initial=[some_link])
            self.amsi_service_instance.provided_links = MockObjectList(initial=[some_link])

            syncstep_fetch_pending.return_value = [self.amsi_inst, self.amsi_service_instance]

            objs = self.sync_step.fetch_pending(deleted = False)
            self.assertEqual(len(objs), 1)

    @requests_mock.Mocker()
    def test_sync_record_instance(self, m):
        with patch.object(FabricService.objects, "get_items") as fabricservice_objects, \
             patch.object(AddressManagerServiceInstance, "get_attribute") as get_attribute, \
             patch.object(Instance.objects, "get_items") as instance_objects:
            fabricservice_objects.return_value = [self.service]

            node = Node(dataPlaneIp = "11.22.33.44")
            instance = Instance(id=3445, node=node)
            instance_objects.return_value = [instance]

            get_attribute.return_value = instance.id

            m.post("http://fabric_host:1234/onos/routeservice/routes",
                   status_code=200,
                   additional_matcher=functools.partial(match_json,{u'prefix': u'5.6.7.8/32', u'nextHop': u'11.22.33.44'}))

            self.sync_step.sync_record(self.amsi_inst)

    @requests_mock.Mocker()
    def test_sync_record_service_instance(self, m):
        with patch.object(FabricService.objects, "get_items") as fabricservice_objects, \
             patch.object(Instance.objects, "get_items") as instance_objects:
            fabricservice_objects.return_value = [self.service]

            node = Node(dataPlaneIp = "55.66.77.88")
            instance = Instance(id=5443, node=node)
            instance_objects.return_value = [instance]

            some_service_instance = ServiceInstance(instance=instance)
            some_link = ServiceInstanceLink(subscriber_service_instance=some_service_instance, provider_service_instance=self.amsi_service_instance)
            some_service_instance.subscribed_links = MockObjectList(initial=[some_link])
            self.amsi_service_instance.provided_links = MockObjectList(initial=[some_link])

            m.post("http://fabric_host:1234/onos/routeservice/routes",
                   status_code=200,
                   additional_matcher=functools.partial(match_json,{u'prefix': u'1.2.3.4/32', u'nextHop': u'55.66.77.88'}))

            self.sync_step.sync_record(self.amsi_service_instance)

    def test_get_subscriber(self):
        some_service_instance = ServiceInstance()
        some_link = ServiceInstanceLink(subscriber_service_instance=some_service_instance,
                                        provider_service_instance=self.amsi_service_instance)
        some_service_instance.subscribed_links = MockObjectList(initial=[some_link])
        self.amsi_service_instance.provided_links = MockObjectList(initial=[some_link])

        self.assertEqual(self.sync_step.get_subscriber(self.amsi_service_instance), some_service_instance)

    def test_get_routes_url(self):
        url = self.sync_step.get_routes_url(self.onos_service)
        self.assertEqual(url, "http://fabric_host:1234/onos/routeservice/routes")

    @requests_mock.Mocker()
    def test_delete_route(self, m):
        m.delete("http://fabric_host:1234/onos/routeservice/routes",
                 status_code=200,
                 additional_matcher=functools.partial(match_json,{u'prefix': u'5.6.7.8/32', u'nextHop': u'55.66.77.88'}))

        route = {u'prefix': u'5.6.7.8/32', u'nextHop': u'55.66.77.88'}

        self.sync_step.delete_route(self.onos_service, route)

    @requests_mock.Mocker()
    def test_post_route(self, m):
        m.post("http://fabric_host:1234/onos/routeservice/routes",
               status_code=200,
               additional_matcher=functools.partial(match_json,{u'prefix': u'5.6.7.8/32', u'nextHop': u'55.66.77.88'}))

        route = {u'prefix': u'5.6.7.8/32', u'nextHop': u'55.66.77.88'}

        self.sync_step.post_route(self.onos_service, route)

if __name__ == "__main__":
    unittest.main()