import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import logging

logger = logging.getLogger(__name__)

class ChatService:
    def __init__(self, model_id: str = None):
        self.model_id = model_id
        self.model = None
        self.tokenizer = None
        if model_id:
            self._load_model()

    def _load_model(self):
        if self.model is not None:
            return
        # Всегда загружаем в 4-бит на GPU
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4"
        )
        logger.info(f"Loading LLM {self.model_id} in 4-bit on GPU...")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True
        )
        self.model.eval()
        logger.info("LLM loaded successfully")

    def generate_response(self, prompt: str, max_new_tokens=512, temperature=0.7) -> str:
        self._load_model()
        device = next(self.model.parameters()).device
        inputs = self.tokenizer(prompt, return_tensors='pt').to(device)
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
            )
        response = self.tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
        return response.strip()