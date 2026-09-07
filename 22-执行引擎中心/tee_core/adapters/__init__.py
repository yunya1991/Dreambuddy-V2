"""Adapters subpackage — concrete ExchangeClient Protocol implementations.

Each adapter:
  * accepts the raw 3rd-party client instance via __init__
  * translates its method signatures to tee_core's Protocol.
"""
