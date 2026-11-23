'use strict';

/**
 * Demo Orders API producer fixture (synthetic).
 *
 * Serves GET /orders/:id returning the candidate response derived from the
 * candidate OpenAPI document that RippleGate passes in. The server is started
 * per test run by the consumer suites; it never talks to the network beyond
 * localhost.
 */

const express = require('express');

const DEFAULT_ORDER = {
  id: 'order-104',
  customer_id: 'cust-900',
  total_cents: 12750,
};

function buildResponse(candidateDocument) {
  // Derive the response shape from the candidate contract's 200 response
  // schema so the fixture always mirrors the registered candidate, not a
  // hardcoded verdict. Supported subset: object properties + required list.
  const schema =
    candidateDocument &&
    candidateDocument.paths &&
    candidateDocument.paths['/orders/{id}'] &&
    candidateDocument.paths['/orders/{id}'].get &&
    candidateDocument.paths['/orders/{id}'].get.responses &&
    candidateDocument.paths['/orders/{id}'].get.responses['200'] &&
    candidateDocument.paths['/orders/{id}'].get.responses['200'].content &&
    candidateDocument.paths['/orders/{id}'].get.responses['200'].content['application/json'] &&
    candidateDocument.paths['/orders/{id}'].get.responses['200'].content['application/json'].schema;

  if (!schema || !schema.properties) {
    throw new Error('candidate document has no supported /orders/{id} GET 200 schema');
  }

  const known = {
    id: 'order-104',
    customer_id: 'cust-900',
    account_id: 'cust-900',
    total_cents: 12750,
    fulfillment_note: 'Packed with care',
    status: 'shipped',
  };

  const body = {};
  for (const [name, prop] of Object.entries(schema.properties)) {
    if (Object.prototype.hasOwnProperty.call(known, name)) {
      const value = known[name];
      body[name] =
        prop && prop.type === 'integer' && typeof value === 'string'
          ? Number(value.replace(/\D/g, '')) || value
          : value;
    } else {
      body[name] = prop && prop.type === 'integer' ? 0 : 'unknown';
    }
  }
  return body;
}

function createServer(candidateDocument) {
  const app = express();
  const responseBody = buildResponse(candidateDocument);

  app.get('/orders/:id', (req, res) => {
    if (req.params.id !== 'order-104') {
      res.status(404).json({ message: 'order not found' });
      return;
    }
    res.status(200).json(responseBody);
  });

  app.get('/healthz', (req, res) => res.status(200).send('ok'));

  return new Promise((resolve) => {
    const server = app.listen(0, '127.0.0.1', () => {
      resolve({ server, port: server.address().port });
    });
  });
}

module.exports = { createServer, buildResponse, DEFAULT_ORDER };

if (require.main === module) {
  const doc = process.argv[2]
    ? require('fs').readFileSync(process.argv[2], 'utf8')
    : null;
  createServer(JSON.parse(doc || '{}')).then(({ server, port }) => {
    console.log(`orders-api fixture listening on 127.0.0.1:${port}`);
  });
}
