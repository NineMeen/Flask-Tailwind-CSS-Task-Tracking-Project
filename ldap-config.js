const ldapConfig = {
  // Server connection settings
  server: {
    url: 'ldap://lapi-uat.symphony.net.th:389',
    bindDN: '', // Admin DN for binding
    bindCredentials: '', // Admin password
    reconnect: true,
    timeout: 30000,
    connectTimeout: 10000,
  },
  
  // Search settings
  search: {
    base: 'OU=WorkTracking,DC=test,DC=net,DC=th',
    scope: 'sub', // Possible values: base, one, sub
    filter: '(objectClass=*)', // Default filter, can be modified as needed
    attributes: ['*'] // Return all attributes
  },
  
  // TLS/SSL settings (if needed)
  tlsOptions: {
    rejectUnauthorized: false, // Set to true in production
    ca: [] // Add CA certificates if needed
  },
  
  // Connection pool settings
  pool: {
    enable: true,
    min: 5,
    max: 10,
    idleTimeout: 300000, // 5 minutes
    validateOnConnect: true
  },
  
  // Retry settings
  retry: {
    enabled: true,
    maxRetries: 3,
    retryDelay: 1000, // 1 second
    maxDelay: 10000 // 10 seconds
  }
};

// Example connection function
async function connectToLDAP() {
  try {
    const ldap = require('ldapjs');
    const client = ldap.createClient({
      url: ldapConfig.server.url,
      reconnect: ldapConfig.server.reconnect,
      timeout: ldapConfig.server.timeout,
      connectTimeout: ldapConfig.server.connectTimeout,
      tlsOptions: ldapConfig.tlsOptions
    });

    // Bind to LDAP server
    await new Promise((resolve, reject) => {
      client.bind(ldapConfig.server.bindDN, ldapConfig.server.bindCredentials, (err) => {
        if (err) {
          reject(err);
        } else {
          resolve();
        }
      });
    });

    return client;
  } catch (error) {
    console.error('Failed to connect to LDAP server:', error);
    throw error;
  }
}

// Example search function
async function searchLDAP(client, searchFilter) {
  return new Promise((resolve, reject) => {
    const opts = {
      filter: searchFilter || ldapConfig.search.filter,
      scope: ldapConfig.search.scope,
      attributes: ldapConfig.search.attributes
    };

    client.search(ldapConfig.search.base, opts, (err, res) => {
      if (err) {
        reject(err);
        return;
      }

      const entries = [];

      res.on('searchEntry', (entry) => {
        entries.push(entry.object);
      });

      res.on('error', (err) => {
        reject(err);
      });

      res.on('end', () => {
        resolve(entries);
      });
    });
  });
}

module.exports = {
  ldapConfig,
  connectToLDAP,
  searchLDAP
};
