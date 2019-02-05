
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


from xossynchronizer.modelaccessor import *
from xossynchronizer.model_policies.policy import Policy

class AddressManagerServiceInstancePolicy(Policy):
    model_name = "AddressManagerServiceInstance"

    def handle_create(self, service_instance):
        return self.handle_update(service_instance)

    def handle_update(self, service_instance):
        if (service_instance.link_deleted_count>0) and (not service_instance.provided_links.exists()):
            # if the last provided_link has just gone away, then self-destruct
            self.logger.info("The last provided link has been deleted -- self-destructing.");
            service_instance.delete()
            return
