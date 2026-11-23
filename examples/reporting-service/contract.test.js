'use strict';

/**
 * reporting-service tolerant consumer contract test.
 *
 * A real executable suite: boots the orders-api fixture with the candidate
 * contract, GETs the order and asserts the registered expectation:
 * `total_cents` is present and finite. Unlike billing, this consumer
 * tolerates new optional response members, so the additive candidate
 * (fulfillment_note added) passes while the rename still breaks it only
 * if total_cents itself changes.
 *
 * Usage: node contract.test.js /path/to/candidate.json
 */

// Resolve the producer fixture both in a checkout (../orders-api) and inside
// the controlled runner container (/suite/producer).
let { createServer } = (() => { try { return require('../orders-api/server.js'); } catch { return require('/suite/producer/server.js'); } })();

const candidatePath = process.argv[2];
if (!candidatePath) {
  console.error('usage: node contract.test.js <candidate.json>');
  process.exit(2);
}

const fs = require('fs');
const candidateDocument = JSON.parse(fs.readFileSync(candidatePath, 'utf8'));

let failures = 0;

function assert(condition, message) {
  if (condition) {
    console.log(`PASS: ${message}`);
  } else {
    failures += 1;
    console.error(`FAIL: ${message}`);
  }
}

async function main() {
  const { server, port } = await createServer(candidateDocument);
  const base = `http://127.0.0.1:${port}`;

  const res = await fetch(`${base}/orders/order-104`, {
    headers: { accept: 'application/json' },
  });
  assert(res.status === 200, `GET /orders/order-104 returns 200 (got ${res.status})`);

  const body = await res.json();

  // reporting dependency registration (registry revision 1):
  //   required_response_fields = ["total_cents"]
  assert(
    Number.isFinite(body.total_cents),
    `response contains numeric total_cents (got ${JSON.stringify(body.total_cents)})`,
  );

  // tolerant consumer: unknown optional members are acceptable
  const extras = Object.keys(body).filter(
    (k) => !['id', 'customer_id', 'total_cents'].includes(k),
  );
  if (extras.length > 0) {
    console.log(`INFO: tolerating optional extra member(s): ${extras.join(', ')}`);
  }

  server.close();
  if (failures > 0) {
    console.error(`reporting-service contract: ${failures} assertion(s) failed`);
    process.exit(1);
  }
  console.log('reporting-service contract: all assertions passed');
  process.exit(0);
}

main().catch((err) => {
  console.error('reporting-service contract: execution error', err);
  process.exit(3);
});
