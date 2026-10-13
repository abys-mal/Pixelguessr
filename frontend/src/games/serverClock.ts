// Presentation clock only; guess validity and all phase changes remain server decisions.
export class ServerClock {
  private offset: number | null = null;
  private target = 0;
  private bestRtt = Infinity;
  private sampledAt = -Infinity;
  private lastLocal = 0;
  private lastServer = 0;

  anchor(serverNow: string, received = performance.now()) {
    if (this.offset !== null) return;
    const server = Date.parse(serverNow);
    if (!Number.isFinite(server)) return;
    this.offset = this.target = server - received;
    this.lastLocal = received;
    this.lastServer = server;
  }

  sample(serverNow: string, sent: number, received = performance.now()) {
    const server = Date.parse(serverNow);
    const rtt = received - sent;
    if (!Number.isFinite(server) || rtt < 0 || rtt > 10000) return;
    // Prefer low-delay samples; expire the selection after a network change/reconnect.
    if (received - this.sampledAt < 30000 && rtt > this.bestRtt * 1.25) return;
    this.bestRtt = rtt;
    this.sampledAt = received;
    this.target = server - (sent + received) / 2;
    if (this.offset === null) {
      this.offset = this.target;
      this.lastLocal = received;
      this.lastServer = server + rtt / 2;
    }
  }

  now(local = performance.now()) {
    if (this.offset === null) return 0;
    // Slew corrections at 10% of elapsed time. Repeated snapshots never reset time.
    const elapsed = Math.max(0, local - this.lastLocal);
    const difference = this.target - this.offset;
    this.offset += Math.sign(difference) * Math.min(Math.abs(difference), elapsed * 0.1);
    this.lastLocal = local;
    this.lastServer = Math.max(this.lastServer, local + this.offset);
    return this.lastServer;
  }
}
