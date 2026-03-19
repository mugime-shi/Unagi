/**
 * usePushNotification — manage Web Push subscription state.
 *
 * Status values:
 *   'loading'      — checking current subscription state
 *   'unsupported'  — browser doesn't support Service Workers or Push API
 *   'idle'         — supported but not subscribed
 *   'subscribed'   — subscription active and saved to backend
 *   'denied'       — user denied notification permission
 *   'error'        — unexpected error during subscribe/unsubscribe
 *
 * How the subscription flow works:
 *   1. Fetch VAPID public key from backend (identifies our server to the push service)
 *   2. Request Notification permission from user
 *   3. Call pushManager.subscribe() — browser registers with push service (Google/Mozilla)
 *      and returns a subscription object with:
 *        endpoint  — unique URL at the push service for this browser/device
 *        keys.p256dh — ECDH public key for payload encryption
 *        keys.auth   — authentication secret for encryption
 *   4. POST subscription to backend → saved in push_subscriptions table
 *   5. Backend sends encrypted HTTP POST to endpoint when prices are ready
 *   6. Service Worker wakes up and shows system notification
 */

import { useEffect, useState } from "react";
import { apiFetch } from "../utils/api";

/** Convert base64url string (no padding) to Uint8Array for applicationServerKey */
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}

export function usePushNotification(area) {
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    checkStatus().then(setStatus);
  }, []);

  async function checkStatus() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      return "unsupported";
    }
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      return sub ? "subscribed" : "idle";
    } catch {
      return "idle";
    }
  }

  async function subscribe() {
    setStatus("loading");
    try {
      // 1. Get VAPID public key from backend
      const keyRes = await apiFetch("/api/v1/notify/vapid-public-key");
      if (!keyRes.ok)
        throw new Error("Push notifications not configured on server");
      const { public_key } = await keyRes.json();

      // 2. Request notification permission
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setStatus("denied");
        return;
      }

      // 3. Subscribe via browser Push API
      //    applicationServerKey identifies our server to the push service
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true, // required: SW must always show a notification
        applicationServerKey: urlBase64ToUint8Array(public_key),
      });

      // 4. Save subscription to backend
      const subJson = sub.toJSON();
      const saveRes = await apiFetch("/api/v1/notify/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: subJson.endpoint,
          p256dh: subJson.keys.p256dh,
          auth: subJson.keys.auth,
          area,
        }),
      });
      if (!saveRes.ok) throw new Error("Failed to save subscription");

      setStatus("subscribed");
    } catch (err) {
      console.error("[Namazu] Push subscribe error:", err);
      setStatus("error");
    }
  }

  async function unsubscribe() {
    setStatus("loading");
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        // Remove from backend first, then unsubscribe browser
        await apiFetch("/api/v1/notify/subscribe", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: sub.endpoint }),
        });
        await sub.unsubscribe();
      }
      setStatus("idle");
    } catch (err) {
      console.error("[Namazu] Push unsubscribe error:", err);
      setStatus("error");
    }
  }

  return { status, subscribe, unsubscribe };
}
