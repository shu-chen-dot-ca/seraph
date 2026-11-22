/*
A VM's screen, live: noVNC's client (RFB) draws only the screen into the box, scaled to fit, none of noVNC's page
around it. A dropped connection tries again every 2 seconds. viewOnly keeps the mouse and keyboard out; it can change
without connecting again (a lock comes and goes while the agent works).

The agent page's Desktop (AgentChat.tsx) uses it view-only. rfbRef, when given, hands the caller the client.

Every screen shown here gets at most 30 updates a second, to keep the browser and the VM light. noVNC asks the VM for
the next update as soon as one arrives; each ask waits until FRAME_MS after the one before. TigerVNC (desktops 2 and
up) would otherwise send updates without being asked (continuous updates), so noVNC doesn't offer that to it.
*/

import RFB from "@novnc/novnc";
import { useEffect, useRef } from "react";

const FRAME_MS = 1000 / 30;
// noVNC's pseudo-encoding for continuous updates (core/encodings.js).
const CONTINUOUS_UPDATES = -313;
// Per websocket: the soonest its next ask may go.
const nextAsk = new WeakMap<object, number>();
const askNow = RFB.messages.fbUpdateRequest;
RFB.messages.fbUpdateRequest = (sock, incremental, x, y, w, h) => {
  const now = performance.now();
  const at = Math.max(now, nextAsk.get(sock) ?? 0);
  nextAsk.set(sock, at + FRAME_MS);
  window.setTimeout(() => askNow(sock, incremental, x, y, w, h), at - now);
};
const offerNow = RFB.messages.clientEncodings;
RFB.messages.clientEncodings = (sock, encodings) => {
  offerNow(sock, encodings.filter((each) => each !== CONTINUOUS_UPDATES));
};

export default function LiveDesktop(props: { url: string; viewOnly: boolean; className?: string; rfbRef?: { current: RFB | null } }) {
  const boxRef = useRef<HTMLDivElement>(null);
  // The connection now, or null between tries: the caller's ref when it passed one.
  const ownRef = useRef<RFB | null>(null);
  const rfbRef = props.rfbRef ?? ownRef;
  // Read by each new connection, so one made while locked starts locked.
  const viewOnlyRef = useRef(props.viewOnly);

  // Declared before the connection below, so the first connection already reads the right value.
  useEffect(() => {
    viewOnlyRef.current = props.viewOnly;
    if (rfbRef.current !== null) {
      rfbRef.current.viewOnly = props.viewOnly;
    }
  }, [props.viewOnly, rfbRef]);

  useEffect(() => {
    const box = boxRef.current;
    if (box === null) {
      return;
    }
    let stopped = false;
    let timer = 0;
    // An arrow function, not a declaration: it keeps box narrowed to not null.
    const connect = () => {
      const rfb = new RFB(box, props.url);
      rfb.viewOnly = viewOnlyRef.current;
      rfb.scaleViewport = true;
      rfb.focusOnClick = !viewOnlyRef.current;
      rfb.background = "black";
      rfb.addEventListener("disconnect", () => {
        // A disconnected RFB is done for good: the next try is a new one. The old one's event can come after a new
        // one was made (a new url): that one stays.
        if (rfbRef.current === rfb) {
          rfbRef.current = null;
        }
        if (!stopped) {
          timer = window.setTimeout(connect, 2000);
        }
      });
      rfbRef.current = rfb;
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      if (rfbRef.current !== null) {
        rfbRef.current.disconnect();
        rfbRef.current = null;
      }
    };
  }, [props.url, rfbRef]);

  return <div ref={boxRef} className={props.className} />;
}
