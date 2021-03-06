#!/usr/bin/env python
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

"""Forculus Library.

Code to apply threshold crypto to secure messages while deriving utility on
popular messages.
"""

import base64
import binascii
import csv
import datetime
import pprint
import random
import sys

from Crypto.Cipher import AES
from Crypto.Hash import HMAC
from Crypto.Hash import SHA256

from struct import pack
from struct import unpack


class Config(object):
  """Forculus configuration parameters.
  """
  def __init__(self):
    self.threshold = 20

  @staticmethod
  def from_csv(f):
    """Read the Forculus parameters from a CSV file.

    Args:
      f: file handle

    Returns:
      Params instance.

    Raises:
      Exception: when the file is malformed.
    """
    c = csv.reader(f)
    ok = False
    p = Config()
    for i, row in enumerate(c):

      if i == 0:
        if row != ['threshold']:
          raise Exception('Header %s is malformed; expected "threshold"' % row)

      elif i == 1:
        try:
          # NOTE: May raise exceptions
          p.threshold = int(row[0])
        except (ValueError, IndexError) as e:
          raise Exception('Row is malformed: %s' % e)
        ok = True

      else:
        raise Exception('Params file should only have two rows')

    if not ok:
      raise Exception("Expected second row with params")

    return p

def _log(string):
  logging_flag = False  # set to True for logging, False otherwise
  if logging_flag:
    if isinstance(string, dict):
      print >> sys.stderr, "[" + str(datetime.datetime.now()) + "]"
      pp = pprint.PrettyPrinter(indent=2, stream=sys.stderr)
      pp.pprint(string)
    else:
      print >> sys.stderr, "[" + str(datetime.datetime.now()) + "]\t" + string


ZERO_HMAC = HMAC.new("0"*160, digestmod=SHA256)
def _ro_hmac(msg, h=None):
  """Implements random oracle H as HMAC-SHA256 with the all-zero key.

  Input is message string and output is a 32-byte sequence containing the HMAC
  value.

  Args:
    msg: Input message string.
    h: An optional instance of HMAC to use. If None a new zeroed-out instance
       will be used.

  Returns:
    bytes: Random Oracle output (32 bytes).
  """
  if h is None:
    h = ZERO_HMAC.copy()
  h.update(msg)
  return h.digest()

# Simple function to unpack bytes from a big-endian byte string into an integer.
def _unpack_bytes(string):
  return int(binascii.hexlify(string), 16)


# Simple function to pack an integer into a big-endian byte string.
# (base 256 effectively). If |min_length| > 0 then the returned string
# will have length at least |min_length|. Zero bytes will be pre-pended
# if necessary.
def _pack_into_bytes(integer, min_length=16):
  s = '%x' % integer
  if len(s) % 2 == 1:
    s = '0' + s
  string = binascii.unhexlify(s)
  if min_length > 0 and len(string) < min_length:
    string = str(bytearray([0] * (min_length- len(string)))) + string
  return string

def _DE_enc(key, msg):
  """Implements deterministic encryption.

  IV is deterministically computed as H(0, msg) truncated to 128 bits
  AES is used in CBC mode
  Both IV and the rest of the ciphertext are returned

  Args:
    key: The key used in DE.
    msg: The message to encrypt.

  Returns:
    iv: Initialization vector
    ciphertext: Rest of the ciphertext
  """
  iv = _ro_hmac("0"+msg)[:16]
  # AES in CBC mode with IV = HMACSHA256(0,m)
  obj = AES.new(key, AES.MODE_CBC, iv)
  ciphertext = obj.encrypt(_CBC_pad_msg(msg))
  return iv, ciphertext


# Implements simple padding to multiple of 16 bytes.
def _CBC_pad_msg(msg):
  length = len(msg) + 1  # +1 for last padding length byte
  if length % 16 == 0:
    return msg + '\x01'
  plength = 16 - (length % 16) + 1  # +1 for last padding length byte
  padding = '\x00' * (plength - 1) + pack('b', plength)
  return msg + padding


# Removes simple padding.
def _CBC_remove_padding(msg):
  plength = unpack('b', msg[-1])[0]  # unpack returns a tuple
  return msg[:-plength]


# Simple function to decrypt message given key, iv, and ciphertext.
def _DE_dec(key, iv, ciphertext):
  obj = AES.new(key, AES.MODE_CBC, iv)
  msg = obj.decrypt(ciphertext)
  return _CBC_remove_padding(msg)


def _egcd(b, n):
  """Performs the extended Euclidean algorithm.

  Args:
    b: Input
    n: Modulus

  Returns:
    g, x, y: such that ax + by = g = gcd(a, b)
  """
  x0, x1, y0, y1 = 1, 0, 0, 1
  while n != 0:
    q, b, n = b // n, n, b % n
    x0, x1 = x1, x0 - q * x1
    y0, y1 = y1, y0 - q * y1
  return  b, x0, y0


# Returns the multiplicative inverse of b mod n if it exists.
def _mult_inv(b, n):
  g, x, _ = _egcd(b, n)
  if g == 1:
    return x % n


# Returns x such that x * b = a mod q.
def _div(q, a, b):
  return (a * _mult_inv(b, q)) % q


# Performs lagrange interpolation and returns constant term of the polyonmial
# Tuples are of the form (x_i, y_i)
def _compute_c0_lagrange(tuples, threshold, q):
  x = [0 for i in xrange(0, threshold)]
  y = [0 for i in xrange(0, threshold)]
  count = 0

  # Add tuples into arrays x and y
  for member in tuples:
    x[count] = int(member[0])
    y[count] = int(member[1])
    count += 1
    if count >= threshold:
      break

  _log("X: " + ", ".join(["%f"] * len(x)) % tuple(x))
  _log("Y: " + ", ".join(["%f"] * len(y)) % tuple(y))

  prod_xi = 1
  for i in xrange(0, threshold):
    prod_xi = (prod_xi  * x[i]) % q

  _log("prod_xi 0x%x" % prod_xi)

  temp_sum = 0
  for i in xrange(0, threshold):
    prod_yjyi = 1
    for j in xrange(0, threshold):
      if i == j:
        continue
      prod_yjyi = (prod_yjyi * (x[j] - x[i])) % q
    product = (x[i] * prod_yjyi) % q
    quotient = _div(q, y[i], product)
    temp_sum = (temp_sum + quotient) % q

  _log("temp_sum 0x%x" % temp_sum)
  return (prod_xi * temp_sum) % q

class _Forculus(object):
  """Private Forculus class with relevant helper functions.
  The public API is exposed through the subclasses ForculusInserter
  and ForculusEvaluator.
  """

  def __init__(self, threshold):
    # Parameters
    if threshold is None:
      self.threshold = 100
    else:
      self.threshold = threshold
    # TODO(pseudorandom):
    # prime q
    # field F_q
    # hash function SlowHash
    # global parameter GlobalParam
    # Params
    self.q = 2**160+7  # Prime
    # self.q = 37  # Prime (FOR TESTING ONLY)
    # self.Fq = GF(self.q)  # Field
    self.eparam = 1  # TODO(pseudorandom): eparam must be fetched from file
    random.seed()
    # For performance reasons we cache the coefficients, iv, and ciphertext
    # corresponding to to a plaintext so we don't have to recompute them. The
    # keys to the dictionary are plaintext and the values are a tuple consisting
    # of the coeeficient list, the iv, and the ciphertext
    self.cache = {}

  #
  # INTERNAL FUNCTIONS
  #
  def _Encrypt(self, ptxt):
    # For performance reasons we create a single instance of HMAC and re-use
    # it for each of the coefficients.
    h = ZERO_HMAC.copy()
    if ptxt in self.cache:
      c, iv, ctxt = self.cache[ptxt]
    else:
      c = [0] * self.threshold
      # Notice we do a double round of HMAC here. First we create a key
      # by using the ZERO_HMAC to hash the plain text.
      ckey = _ro_hmac(str(1) + str(self.eparam) + ptxt, h)
      # Then we create a new HMAC object using this key.
      # This single HMAC object is used to generate each of the coefficients.
      h = HMAC.new(ckey, digestmod=SHA256)
      for i in xrange(0, self.threshold):
        c[i] = _unpack_bytes(_ro_hmac(str(i), h)) % self.q
      iv, ctxt = _DE_enc(_pack_into_bytes(c[0])[:16], ptxt)
      self.cache[ptxt] = (c, iv, ctxt)

    _log("Key, i.e., c0: %d" % c[0])
    _log("Rest of coefficients: " + ", ".join(["%d"] * (self.threshold-1)) %
         tuple(c[1:]))

    eval_point = random.randrange((self.threshold**2) * (2 ** 80))
    eval_point = _unpack_bytes(_ro_hmac(str(eval_point), h)) % self.q
    _log("Eval point: %d" % eval_point)

    # Horner polynomial eval
    temp_eval = 0
    for i in xrange(self.threshold - 1, 0, -1):
      temp_eval = ((temp_eval + c[i]) * eval_point) % self.q
      _log("(In loop) i = %d, c[i] = %d, temp_eval = %d" % (i, c[i], temp_eval))
    temp_eval = (temp_eval + c[0]) % self.q
    _log("Eval data: %d" % temp_eval)
    # Return:
    #   IV, ciphertext, random evaluation point, evaluation value, msg. derived
    #   key i.e., C0.
    # message-derived key for debug purposes only.
    return(iv, ctxt, eval_point, temp_eval, c[0])

  def _Decrypt(self, iv, ctxt, dict_vals):
    # Use first self.threshold values to do Lagrange interpolation
    # TODO(pseudorandom, rudominer): Ensure that first self.threshold values
    # have unique interpolation points (otherwise the interpolation will fail
    # ungracefully).
    c0 = _compute_c0_lagrange(dict_vals, self.threshold, self.q)
    _log("c0: 0x%x" % c0)
    ptxt = _DE_dec(_pack_into_bytes(int(c0))[:16], iv, ctxt)
    _log("ptxt: %s" % ptxt)
    return ptxt

class ForculusInserter(_Forculus):
  """ A ForculusInserter is used to insert entries into a Forculus-encrypted
  database.
  """
  def __init__(self, threshold, e_db):
    """ Constructs a new ForculusInserter with the given threshold and the
    given database.

    Args:
      threshold {int}: A positive integer that will be the threshold used
      for threshold encryption.

      e_db {writer}: The database into which encrypted entries will be written.
      Any object with a write() method. If e_db is a file object
      it must have been opened for writing with the 'b' flag.
    """
    super(ForculusInserter, self).__init__(threshold)
    self.edb_writer = csv.writer(e_db)

  def Insert(self, ptxt, additional_encryption_func=None):
    """ Insert an encrypted version of the given plaintext into the database.

    Args:
      ptxt {string}: The plaintext to insert.

      additional_encryption_func {function}: If this is not None then the
      encryption function will be applied to each row of data just before
      writing to e_db. The function should accept a string and return a tuple of
      one or more strings representing the ciphertext. In this case a
      corresponding decryption function must be passed to
      ForculusEvaluator.ComputeAndWriteResults().
    """
    iv, ctxt, eval_point, eval_value, key = self._Encrypt(ptxt)
    data_to_write = [base64.b64encode(iv), base64.b64encode(ctxt),
                     eval_point, eval_value]
    if additional_encryption_func is not None:
      # Express the data-to-write as a single string with comma-separated
      # fields. Then encrypt that string, receiving a tuple of strings
      # representing the ciphertext. We use that tuple as the data-to-write.
      data_to_write = additional_encryption_func(
          ",".join(map(str,data_to_write)))
    self.edb_writer.writerow(data_to_write)

class ForculusEvaluator(_Forculus):
  """ A ForculusEvaluator is used to evaluate a Forculus-encrypted database
  that was created with a ForculusInserter.
  """
  def __init__(self, threshold, e_db):
    """ Constructs a new ForculusEvaluator with the given threshold and
    the given database. The database must have been generated using
    a ForculusInserter and it is essential that the same value of |threshold|
    be passed as was used to create the database. Failure to do this will
    result in the decryption failing.

    Args:
      threshold {int}: A positive integer that was the threshold used
      for threshold encryption when the database was created.

      e_db {iterator}: The database from which encrypted entries will be read.
      Any object which supports the iterator protocol and returns a string each
      time its next() method is called. If e_db is a file object
      it must have been opened for reading with the 'b' flag.
    """
    super(ForculusEvaluator, self).__init__(threshold)
    self.edb_reader = csv.reader(e_db)

  def ComputeAndWriteResults(self, r_db, additional_decryption_func=None):
    """ Reads the entries from the encrypted database and decrypts any
    entries that occur at least |threshold| times. The dycrpted plaintexts
    are written to the result database along with there counts.

    Args:
      r_db {writer}: The database into which decrypted results will be written.
      Any object with a write() method. If r_db is a file object
      it must have been opened for writing with the 'b' flag.

      additional_decryption_func {function}: If this is not None then the
      decryption function will be applied to each row of data just after reading
      it from |e_db|. The function should accept a tuple of strings representing
      the ciphertext and return a single string representing the plain text.
      The decryption function should be the inverse of the encryption function
      passed to the ForculusInserter.Insert() method.
    """
    dictionary = {}
    for i, row in enumerate(self.edb_reader):
      if additional_decryption_func is not None:
        # The tuple read from e_db represents a cipher text. Pass the elements
        # of that tuple as arguments to the decryption function receiving
        # back the plaintext which is a single string that is a comma-separated
        # list of fields. Split that string into fields and use that as
        # the value of the read row.
        row =  additional_decryption_func(*row).split(",")
      (iv, ctxt, eval_point, eval_data) = row
      key = iv + " " + ctxt
      if key in dictionary:
        dictionary[key].append([eval_point, eval_data])
      else:
        dictionary[key] = [[eval_point, eval_data]]
    _log("Dict")
    _log(dictionary)
    rdb_writer = csv.writer(r_db)
    # For each element in dict with >= self.threshold points, do
    # Lagrange interpolation to retrieve key
    for keys in dictionary:
      if len(dictionary[keys]) >= self.threshold:
        # Recover iv and ctxt first
        [iv, ctxt] = map(base64.b64decode, keys.strip().split(" "))
        ptxt = self._Decrypt(iv, ctxt, dictionary[keys])
        rdb_writer.writerow([ptxt, len(dictionary[keys])])
