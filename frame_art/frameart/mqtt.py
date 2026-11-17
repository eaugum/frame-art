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

from . import __version__, events

log = logging.getLogger(__name__)

BASE = "frame_art"
DISCOVERY = "homeassistant"
AVAILABILITY = BASE + "/status"
LOOK_SECONDS = 5
PICTURE_WIDTH = 1280  # the image entity: big enough for a card, small enough for MQTT
ACTIVITIES = ["off", "app", "art", "morning", "tonight", "saver", "music", "unknown"]  # Rotation.activity()

MODES = {"shuffle": "Shuffle", "fixed": "Fixed picture"}  # -> the select's options
SWITCHES = {  # settings
    "morning": "Morning picture",
    "tonight": "Tonight's show",
    "paused": "Pause the rotation",
    "screensaver": "Screensaver",
    "screensaver_stasera": "Stasera in the screensaver",
    "music": "Follow the music",
    "music_home_only": "Only when someone is home",  # Follow the music
    "tv_timer_off": "Keep the TV's timer and light sensor off",
    "away_off": "Turn the TV off when nobody is home",
}
# The TV's own Art Mode settings (AUG-1722), read from the TV and changed on it; unavailable while the TV is off
TV_NUMBERS = {  # item -> (name, min, max, icon)
    "brightness": ("TV brightness in Art Mode", 0, 10, "mdi:brightness-6"),
    "color_temperature": ("TV colour temperature in Art Mode", -5, 5, "mdi:thermometer"),
    "motion_sensitivity": ("TV motion sensitivity", 1, 3, "mdi:motion-sensor"),
}
TV_TIMER = ["off", "5", "15", "30", "60", "120", "240"]  # what the 2022 Frame says Sleep After can be


def _timer_name(value):
    return "Off" if value == "off" else value + " min"
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
        on_tv = {"device": device, "availability_mode": "all", "entity_category": "config",
                 "availability": [{"topic": AVAILABILITY},
                                  {"topic": BASE + "/tv_on", "payload_available": "ON",
                                   "payload_not_available": "OFF"}]}

        def entity(component, key, name, base=common, **extra):
            topic = "%s/%s/%s_%s/config" % (DISCOVERY, component, BASE, key)
            return topic, dict(base, name=name, unique_id="%s_%s" % (BASE, key),
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
        # What the TV does, for Home Assistant's history and automations (AUG-1524)
        out.append(entity("binary_sensor", "tv_on", "TV on", device_class="power", state_topic=BASE + "/tv_on"))
        out.append(entity("binary_sensor", "art_mode", "Art Mode", icon="mdi:image-frame",
                          state_topic=BASE + "/art_mode"))
        out.append(entity("sensor", "activity", "Activity", icon="mdi:television-guide", device_class="enum",
                          options=ACTIVITIES, state_topic=BASE + "/activity"))
        # The TV on and off (AUG-1722); its state is binary_sensor.frame_art_tv_on's, unknown until seen
        out.append(entity("switch", "tv_power", "TV", icon="mdi:television", state_topic=BASE + "/tv_on",
                          command_topic=BASE + "/tv_power/set", payload_on="ON", payload_off="OFF"))
        for item, (name, low, high, icon) in TV_NUMBERS.items():
            out.append(entity("number", "tv_" + item, name, base=on_tv, icon=icon, min=low, max=high, step=1,
                              mode="slider", state_topic="%s/tv/%s" % (BASE, item),
                              command_topic="%s/tv_%s/set" % (BASE, item)))
        out.append(entity("select", "tv_motion_timer", "TV Sleep After", base=on_tv, icon="mdi:timer-sand",
                          options=[_timer_name(v) for v in TV_TIMER], state_topic=BASE + "/tv/motion_timer",
                          command_topic=BASE + "/tv_motion_timer/set"))
        out.append(entity("switch", "tv_light_sensor", "TV light sensor", base=on_tv, icon="mdi:brightness-auto",
                          state_topic=BASE + "/tv/brightness_sensor_setting",
                          command_topic=BASE + "/tv_light_sensor/set", payload_on="ON", payload_off="OFF"))
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
        for key, on in (("tv_on", s["tv"]["power"]), ("art_mode", s["tv"]["art_mode"])):
            out["%s/%s" % (BASE, key)] = "None" if on is None else "ON" if on else "OFF"  # None: unknown
        out[BASE + "/activity"] = s["tv"]["activity"]
        if s["category"]:  # what's ticked is one category's sources
            out[BASE + "/category"] = s["category"]
        for key in SWITCHES:
            out["%s/%s" % (BASE, key)] = "ON" if st.get(key) else "OFF"
        for item, value in self.rot.art_settings().items():
            if item in TV_NUMBERS:
                out["%s/tv/%s" % (BASE, item)] = value
            elif item == "motion_timer":
                out[BASE + "/tv/motion_timer"] = _timer_name(value)
            elif item == "brightness_sensor_setting":
                out[BASE + "/tv/brightness_sensor_setting"] = "ON" if value == "on" else "OFF"
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
                    events.add("mqtt", "failed", "%s didn't happen" % what)
            except Exception as e:
                log.info("MQTT: %s failed (%s: %s)", what, type(e).__name__, e)
                events.add("mqtt", "failed", "%s: %s: %s" % (what, type(e).__name__, e))
        task = asyncio.create_task(go())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def command(self, topic, payload):
        name = topic[len(BASE) + 1:]
        log.info("MQTT: %s %s", name, payload)
        events.add("mqtt", name.rsplit("/", 1)[0], payload, why="Home Assistant (MQTT)")
        with events.because("Home Assistant (MQTT %s)" % name):
            self._command(name, payload)

    def _command(self, name, payload):
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
            elif name.startswith("tv_") and name.endswith("/set") and name[3:-4] in TV_NUMBERS:
                self._tv(name[3:-4], str(int(float(payload))))
            elif name == "tv_power/set":
                if payload == "ON":
                    self.run_task(self.rot.wake_up(), "turning the TV on")
                else:
                    self.run_task(self.rot.power_off(), "turning the TV off")
            elif name == "tv_motion_timer/set":
                self._tv("motion_timer", {_timer_name(v): v for v in TV_TIMER}[payload])
            elif name == "tv_light_sensor/set":
                self._tv("brightness_sensor_setting", "on" if payload == "ON" else "off")
            elif name.endswith("/set") and name[:-4] in SWITCHES:
                self.rot.set_settings({name[:-4]: payload == "ON"})
        except (ValueError, TypeError, KeyError) as e:
            log.info("MQTT: %s %s: %s", name, payload, e)
            events.add("mqtt", "failed", "%s %s: %s" % (name, payload, e))

    def _tv(self, item, value):
        self.run_task(self.rot.set_tv_settings({item: value}), "the TV's %s" % item)

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
