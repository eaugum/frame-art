"""Frame Art as a device in Home Assistant, through MQTT discovery (AUG-1493).

The broker comes from the Supervisor (services: mqtt:want in config.yaml), so there's nothing to fill in; outside Home
Assistant, mqtt_host (and mqtt_port, mqtt_username, mqtt_password) in the options. Without a broker it does nothing.

The state is published retained whenever it changes (looked at every few seconds, so a change from the page, the API
or the timer comes along too), and commands from Home Assistant go to the same methods as the add-on's page.
"""
import asyncio
import io
import json
import logging
import os
import urllib.request

import aiomqtt
from PIL import Image

from . import __version__

log = logging.getLogger(__name__)

BASE = "frame_art"
DISCOVERY = "homeassistant"
AVAILABILITY = BASE + "/status"
LOOK_SECONDS = 5
PICTURE_WIDTH = 1280  # the image entity: big enough for a card, small enough for MQTT

MODES = {"shuffle": "Shuffle", "fixed": "Fixed picture"}  # -> the select's options
SWITCHES = {  # settings
    "morning": "Morning picture",
    "tonight": "Tonight's show",
    "screensaver": "Screensaver",
    "screensaver_stasera": "Stasera in the screensaver",
    "music": "Follow the music",
    "music_home_only": "Only when someone is home",
}
BUTTONS = {  # id -> (name, icon)
    "next": ("Next picture", "mdi:image-refresh"),
    "morning_now": ("Morning picture now", "mdi:weather-sunset-up"),
    "tonight_now": ("Tonight's show now", "mdi:television-classic"),
    "artmode": ("Art Mode now", "mdi:image-frame"),
}


def broker(cfg):
    """{host, port, username, password} from the Supervisor or the options, or None."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:
        try:
            req = urllib.request.Request("http://supervisor/services/mqtt",
                                         headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read()).get("data") or {}
            if data.get("host"):
                return {"host": data["host"], "port": int(data.get("port") or 1883),
                        "username": data.get("username"), "password": data.get("password")}
        except Exception as e:
            log.info("no MQTT broker from the Supervisor (%s); is Mosquitto installed?", e)
    if cfg.get("mqtt_host"):
        return {"host": cfg["mqtt_host"], "port": int(cfg.get("mqtt_port") or 1883),
                "username": cfg.get("mqtt_username"), "password": cfg.get("mqtt_password")}
    return None


class Device:
    def __init__(self, rotation, conn):
        self.rot = rotation
        self.conn = conn
        self.sent = {}  # topic -> the payload last published
        self.picture_at = None
        self.tasks = set()

    # MARK: - Discovery

    def configs(self):
        device = {"identifiers": [BASE], "name": "Frame Art", "manufacturer": "eaugum/frame-art",
                  "model": "Art Mode for The Frame", "sw_version": __version__}
        common = {"device": device, "availability_topic": AVAILABILITY}

        def entity(component, key, name, **extra):
            topic = "%s/%s/%s_%s/config" % (DISCOVERY, component, BASE, key)
            return topic, dict(common, name=name, unique_id="%s_%s" % (BASE, key),
                               default_entity_id="%s.%s_%s" % (component, BASE, key), **extra)

        out = []
        for key, (name, icon) in BUTTONS.items():
            out.append(entity("button", key, name, icon=icon, command_topic="%s/%s/press" % (BASE, key)))
        out.append(entity("select", "mode", "Mode", icon="mdi:shuffle-variant",
                          options=list(MODES.values()),
                          state_topic=BASE + "/mode", command_topic=BASE + "/mode/set"))
        out.append(entity("select", "category", "Category", icon="mdi:shape", options=self.rot.categories,
                          state_topic=BASE + "/category", command_topic=BASE + "/category/set"))
        out.append(entity("number", "interval", "Interval", icon="mdi:timer-outline", min=5, max=1440, step=5,
                          mode="box", unit_of_measurement="min", state_topic=BASE + "/interval_minutes",
                          command_topic=BASE + "/interval_minutes/set"))
        for key, name in SWITCHES.items():
            out.append(entity("switch", key, name, state_topic="%s/%s" % (BASE, key),
                              command_topic="%s/%s/set" % (BASE, key), payload_on="ON", payload_off="OFF"))
        out.append(entity("sensor", "showing", "Picture", icon="mdi:image", state_topic=BASE + "/showing",
                          value_template="{{ value_json.title }}", json_attributes_topic=BASE + "/showing"))
        out.append(entity("sensor", "wanted", "In charge", icon="mdi:crown-outline", state_topic=BASE + "/wanted"))
        out.append(entity("image", "picture", "The picture on the wall", image_topic=BASE + "/picture",
                          content_type="image/jpeg"))
        return out

    # MARK: - State

    def states(self):
        s = self.rot.status()
        st = s["settings"]
        label = s.get("showing") or ""
        source, _, title = label.partition(": ") if ": " in label else ("", "", label)
        out = {
            BASE + "/mode": MODES.get(s["mode"], MODES["shuffle"]),
            BASE + "/interval_minutes": str(int(st["interval_minutes"])),
            BASE + "/wanted": s["wanted"],
            BASE + "/showing": json.dumps({"title": title or "Not changed yet", "source": source or None,
                                           "category": s["source_categories"].get(source),
                                           "changed": s["changed"] or None, "next": s["next"],
                                           "fixed_until": (s["fixed"] or {}).get("until")}, ensure_ascii=False),
        }
        if s["category"]:  # what's ticked is one category's sources
            out[BASE + "/category"] = s["category"]
        for key in SWITCHES:
            out["%s/%s" % (BASE, key)] = "ON" if st.get(key) else "OFF"
        return out

    def picture(self):
        if not os.path.exists(self.rot.showing_path):
            return None
        img = Image.open(self.rot.showing_path)
        img.draft("RGB", (PICTURE_WIDTH, PICTURE_WIDTH))
        img = img.convert("RGB")
        img.thumbnail((PICTURE_WIDTH, PICTURE_WIDTH))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=80)
        return out.getvalue()

    async def publish_configs(self, client):
        """Discovery."""
        for topic, config in self.configs():
            await client.publish(topic, json.dumps(config, ensure_ascii=False), retain=True)

    async def publish_states(self, client):
        for topic, payload in self.states().items():
            if self.sent.get(topic) != payload:
                await client.publish(topic, payload, retain=True)
                self.sent[topic] = payload
        changed = self.rot.state["changed"]
        if changed != self.picture_at:
            jpeg = await asyncio.to_thread(self.picture)
            if jpeg:
                await client.publish(BASE + "/picture", jpeg, retain=True)
            self.picture_at = changed

    # MARK: - Commands

    def run_task(self, coro, what):
        async def go():
            try:
                ok = await coro
                if ok is False:
                    log.info("MQTT: %s didn't happen (see above)", what)
            except Exception as e:
                log.info("MQTT: %s failed (%s: %s)", what, type(e).__name__, e)
        task = asyncio.create_task(go())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def command(self, topic, payload):
        name = topic[len(BASE) + 1:]
        log.info("MQTT: %s %s", name, payload)
        try:
            if name == "next/press":
                self.run_task(self.rot.change(art_mode=True), "a new picture")
            elif name == "morning_now/press":
                self.run_task(self.rot.change(art_mode=True, what="morning"), "Morgenbildet")
            elif name == "tonight_now/press":
                self.run_task(self.rot.change(art_mode=True, what="tonight"), "tonight's show")
            elif name == "artmode/press":
                self.run_task(self.rot.art_mode(), "Art Mode")
            elif name == "mode/set":
                mode = {v: k for k, v in MODES.items()}.get(payload)
                if mode == "fixed":
                    self.rot.fix_showing()
                elif mode:
                    self.rot.set_settings({"mode": mode})
            elif name == "category/set":
                self.rot.set_settings({"mode": "category", "category": payload})
            elif name == "interval_minutes/set":
                self.rot.set_settings({"interval_minutes": int(float(payload))})
            elif name.endswith("/set") and name[:-4] in SWITCHES:
                self.rot.set_settings({name[:-4]: payload == "ON"})
        except (ValueError, TypeError) as e:
            log.info("MQTT: %s %s: %s", name, payload, e)

    # MARK: - Running

    async def run(self):
        will = aiomqtt.Will(AVAILABILITY, "offline", retain=True)
        async with aiomqtt.Client(self.conn["host"], self.conn["port"], username=self.conn.get("username"),
                                  password=self.conn.get("password"), identifier="frame-art", will=will) as client:
            log.info("MQTT: connected to %s:%s, Frame Art is a device in Home Assistant", self.conn["host"],
                     self.conn["port"])
            await self.publish_configs(client)
            await client.publish(AVAILABILITY, "online", retain=True)
            self.sent, self.picture_at = {}, None
            await client.subscribe(BASE + "/+/set")
            await client.subscribe(BASE + "/+/press")
            looker = asyncio.create_task(self.look(client))
            try:
                async for message in client.messages:
                    self.command(str(message.topic), message.payload.decode(errors="replace"))
                    await self.publish_states(client)
            finally:
                looker.cancel()

    async def look(self, client):
        while True:
            try:
                await self.publish_states(client)
            except aiomqtt.MqttError:
                raise
            except Exception as e:
                log.warning("MQTT: couldn't publish the state (%s: %s)", type(e).__name__, e)
            await asyncio.sleep(LOOK_SECONDS)


async def serve(rotation, cfg):
    """Keeps the connection up for as long as the add-on runs; gives up quietly without a broker."""
    conn = await asyncio.to_thread(broker, cfg)
    if not conn:
        log.info("MQTT: no broker, so not in Home Assistant as a device (install Mosquitto)")
        return
    device = Device(rotation, conn)
    while True:
        try:
            await device.run()
        except aiomqtt.MqttError as e:
            log.info("MQTT: %s; trying again in a minute", e)
        await asyncio.sleep(60)
