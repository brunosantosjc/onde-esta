import json
import requests
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_model import Response

# 🔗 URL do seu backend no Render
BASE_URL = "https://onde-esta.onrender.com"

# =========================
# Launch Request
# =========================
class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        speak_output = "Você pode perguntar onde está alguém. Por exemplo, onde está Bruno."
        return handler_input.response_builder.speak(speak_output).ask(speak_output).response


# =========================
# OndeEstaIntent (Primeira pergunta)
# =========================
class OndeEstaIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("OndeEstaIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        try:
            slots = handler_input.request_envelope.request.intent.slots
            slot_pessoa = slots.get("pessoa")
            if not slot_pessoa or not slot_pessoa.value:
                return handler_input.response_builder.speak(
                    "Não entendi o nome da pessoa."
                ).ask("Pode repetir o nome?").response

            pessoa = slot_pessoa.value.lower()

            # Chamada ao backend /where/<nome>
            url = f"{BASE_URL}/where/{pessoa}"
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                return handler_input.response_builder.speak(
                    f"Não encontrei a localização de {pessoa}."
                ).response

            data = resp.json()
            rua = data.get("rua", "localização desconhecida")

            speak_output = f"{pessoa.capitalize()} está na {rua}. Quer mais detalhes?"
            # Mantém sessão aberta para responder o YesIntent
            return handler_input.response_builder.speak(speak_output).ask("Quer ouvir os detalhes?").response

        except Exception as e:
            print("Erro:", e)
            return handler_input.response_builder.speak(
                "Ocorreu um erro ao buscar a localização."
            ).response


# =========================
# YesIntent (Segunda pergunta)
# =========================
class YesIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.YesIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        # Tenta pegar a pessoa do session_attributes
        session_attr = handler_input.attributes_manager.session_attributes
        pessoa = session_attr.get("ultima_pessoa")
        if not pessoa:
            return handler_input.response_builder.speak(
                "Não sei a quem você se refere. Pergunte primeiro onde está alguém."
            ).response

        try:
            # Chamada ao backend /details/<nome>
            url = f"{BASE_URL}/details/{pessoa}"
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                return handler_input.response_builder.speak(
                    f"Não consegui obter os detalhes de {pessoa} agora."
                ).response

            data = resp.json()
            detalhes = data.get("detalhes", "Detalhes indisponíveis")

            return handler_input.response_builder.speak(detalhes).response

        except Exception as e:
            print("Erro:", e)
            return handler_input.response_builder.speak(
                "Ocorreu um erro ao buscar os detalhes."
            ).response


# =========================
# Help Intent
# =========================
class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        speak_output = "Você pode perguntar, por exemplo, onde está Bruno."
        return handler_input.response_builder.speak(speak_output).ask(speak_output).response


# =========================
# Cancel / Stop
# =========================
class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.CancelIntent")(handler_input) or \
               is_intent_name("AMAZON.StopIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        return handler_input.response_builder.speak("Até mais.").response


# =========================
# Fallback
# =========================
class FallbackIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        speak_output = "Não entendi. Tente dizer, por exemplo, onde está Bruno."
        return handler_input.response_builder.speak(speak_output).ask(speak_output).response


# =========================
# Skill Builder
# =========================
sb = SkillBuilder()

sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(OndeEstaIntentHandler())
sb.add_request_handler(YesIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(FallbackIntentHandler())

lambda_handler = sb.lambda_handler()
