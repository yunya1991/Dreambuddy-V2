const dns = require('dns');

function isOkxHost(hostname) {
  const h = String(hostname || '').trim().toLowerCase();
  return h === 'okx.com' || h.endsWith('.okx.com');
}

const resolver = new dns.Resolver();
resolver.setServers(['1.1.1.1', '1.0.0.1']);

function resolve4ViaResolver(hostname, callback) {
  if (!isOkxHost(hostname)) {
    return dns.__orig_resolve4(hostname, callback);
  }
  resolver.resolve4(hostname, (err, addresses) => {
    if (err || !Array.isArray(addresses) || addresses.length === 0) {
      return dns.__orig_resolve4(hostname, callback);
    }
    return callback(null, addresses);
  });
}

function lookupViaResolver(hostname, options, callback) {
  if (!isOkxHost(hostname)) {
    return dns.__orig_lookup(hostname, options, callback);
  }
  const opts = (typeof options === 'object' && options) ? options : {};
  const wantAll = Boolean(opts.all);
  resolver.resolve4(hostname, (err, addresses) => {
    if (err || !Array.isArray(addresses) || addresses.length === 0) {
      return dns.__orig_lookup(hostname, options, callback);
    }
    if (wantAll) {
      const out = addresses.map((a) => ({ address: a, family: 4 }));
      return callback(null, out);
    }
    return callback(null, addresses[0], 4);
  });
}

if (!dns.__orig_lookup) {
  dns.__orig_lookup = dns.lookup;
  dns.lookup = lookupViaResolver;
}

if (!dns.__orig_resolve4) {
  dns.__orig_resolve4 = dns.resolve4;
  dns.resolve4 = resolve4ViaResolver;
}

if (dns.promises && !dns.promises.__orig_lookup) {
  dns.promises.__orig_lookup = dns.promises.lookup;
  dns.promises.lookup = (hostname, options) => {
    return new Promise((resolve, reject) => {
      lookupViaResolver(hostname, options, (err, address, family) => {
        if (err) return reject(err);
        if (Array.isArray(address)) return resolve(address);
        if (typeof options === 'object' && options && options.all) return resolve([{ address, family }]);
        return resolve({ address, family });
      });
    });
  };
}

if (dns.promises && !dns.promises.__orig_resolve4) {
  dns.promises.__orig_resolve4 = dns.promises.resolve4;
  dns.promises.resolve4 = (hostname) => {
    return new Promise((resolve, reject) => {
      resolve4ViaResolver(hostname, (err, addresses) => {
        if (err) return reject(err);
        return resolve(addresses);
      });
    });
  };
}
