# Copyright 2016 The Fuchsia Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

include_directories(BEFORE PRIVATE "${CMAKE_SOURCE_DIR}/third_party/boringssl/include")

add_library(cobalt_crypto base64.cc cipher.cc errors.cc hash.cc mac.cc
            random.cc)
add_cobalt_dependencies(cobalt_crypto)

# Build an executable test binary. Include gtest headers at compile time
# and gtest libraries at link time. Write the executable to the
# out/gtests directory
add_executable(cobalt_crypto_test base64_test.cc cipher_test.cc hash_test.cc
               mac_test.cc random_test.cc)
target_link_libraries(cobalt_crypto_test cobalt_crypto)
add_cobalt_test_dependencies(cobalt_crypto_test ${DIR_GTESTS})
