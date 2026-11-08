import os

from django import forms
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from .models import Collection, UserProfile, LLMModel, EmbeddingModel, Document

ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.doc', '.pptx', '.xlsx', '.xls', '.ods',
                     '.html', '.htm', '.epub', '.odt', '.rtf', '.csv', '.md', '.txt']
                     
class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

    def __init__(self, attrs=None):
        default_attrs = {'multiple': True}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    def value_from_datadict(self, data, files, name):
        if hasattr(files, 'getlist'):
            return files.getlist(name)
        return [files.get(name)]


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text=_('Обязательно для восстановления пароля'))

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
            # FIX: профиль создаётся сигналом post_save (signals.py) —
            # повторный create здесь давал IntegrityError при регистрации.
            # Только выставляем trial-статус у уже созданного профиля.
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if profile.account_status != 'trial':
                profile.account_status = 'trial'
                profile.save()
        return user


class UserProfileForm(forms.ModelForm):
    huggingface_token = forms.CharField(widget=forms.PasswordInput(render_value=True), required=False)
    telegram = forms.CharField(required=False)
    llm_model_id = forms.ModelChoiceField(
        queryset=LLMModel.objects.filter(is_active=True, downloaded=True),
        required=False,
        label=_('LLM модель для чата')
    )
    embedding_model_id = forms.ModelChoiceField(
        queryset=EmbeddingModel.objects.filter(is_active=True, downloaded=True),
        required=False,
        label=_('Модель эмбеддингов')
    )

    class Meta:
        model = UserProfile
        fields = ['work_place', 'telegram', 'huggingface_token']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance:
            self.initial['llm_model_id'] = self.instance.llm_model_id
            self.initial['embedding_model_id'] = self.instance.embedding_model_id

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.huggingface_token = self.cleaned_data['huggingface_token']
        profile.telegram = self.cleaned_data['telegram']
        profile.llm_model = self.cleaned_data['llm_model_id']
        profile.embedding_model = self.cleaned_data['embedding_model_id']
        if commit:
            profile.save()
        return profile


class CollectionForm(forms.ModelForm):
    class Meta:
        model = Collection
        fields = ['name', 'description', 'is_public', 'chunking_strategy', 'chunk_size', 'chunk_overlap', 'auto_process']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: Юридические документы'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Опишите коллекцию'}),
            'chunking_strategy': forms.Select(attrs={'class': 'form-select', 'id': 'chunkingStrategy'}),
            'chunk_size': forms.NumberInput(attrs={'class': 'form-control', 'id': 'chunkSize', 'step': 100, 'min': 100, 'max': 10000}),
            'chunk_overlap': forms.NumberInput(attrs={'class': 'form-control', 'id': 'chunkOverlap', 'step': 50, 'min': 0, 'max': 5000}),
            'auto_process': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_public': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'chunking_strategy': 'Стратегия разделения',
            'chunk_size': 'Размер чанка (символов)',
            'chunk_overlap': 'Перекрытие чанков (символов)',
            'auto_process': 'Автоматическая обработка',
        }
        help_texts = {
            'chunk_size': 'Рекомендуется 500-2000 символов',
            'chunk_overlap': 'Рекомендуется 10-20% от размера чанка',
        }

    def clean(self):
        cleaned_data = super().clean()
        chunk_size = cleaned_data.get('chunk_size')
        chunk_overlap = cleaned_data.get('chunk_overlap')
        if chunk_size and chunk_overlap and chunk_overlap >= chunk_size:
            raise ValidationError(_('Перекрытие чанков должно быть меньше их размера'))
        return cleaned_data


class DocumentUploadForm(forms.Form):
    collection = forms.ModelChoiceField(
        queryset=Collection.objects.none(),
        label=_('Коллекция'),
        widget=forms.HiddenInput()   # скрытое поле, заполняется через JS
    )
    files = forms.FileField(
        widget=MultipleFileInput(attrs={'class': 'form-control', 'style': 'display:none;'}),
        label=_('Файлы')
    )
    title = forms.CharField(
        required=False,
        label=_('Общий заголовок (опционально)'),
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Необязательно'})
    )
    description = forms.CharField(
        required=False,
        label=_('Описание'),
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Описание документа'})
    )
    tags = forms.CharField(
        required=False,
        label=_('Теги (через запятую)'),
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'например: important, draft'})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if user:
            self.fields['collection'].queryset = Collection.objects.filter(owner=user)

    def clean_tags(self):
        tags = self.cleaned_data.get('tags', '')
        if tags:
            return [tag.strip() for tag in tags.split(',') if tag.strip()]
        return []

    def clean_files(self):
        files = self.cleaned_data['files']
        for f in files:
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise forms.ValidationError(f"Недопустимый формат файла: {ext}")
        return files


# ============================================================================
# Форма для редактирования метаданных документа
# ============================================================================
class DocumentEditForm(forms.ModelForm):
    tags = forms.CharField(
        required=False,
        label=_('Теги (через запятую)'),
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'например: important, draft'})
    )

    class Meta:
        model = Document
        fields = ['title', 'description', 'tags']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }

    def clean_tags(self):
        tags = self.cleaned_data.get('tags', '')
        if tags:
            return [tag.strip() for tag in tags.split(',') if tag.strip()]
        return []


# ============================================================================
# Форма для загрузки LLM модели с Hugging Face (только для админов)
# ============================================================================
class LLMModelUploadForm(forms.ModelForm):
    """Форма для добавления LLM модели с Hugging Face Hub"""
    
    class Meta:
        model = LLMModel
        fields = [
            'name', 'display_name', 'model_id', 'model_type',
            'parameter_count', 'quantization', 'is_default', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'qwen2_5_7b_instruct'}),
            'display_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Qwen2.5-7B-Instruct'}),
            'model_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Qwen/Qwen2.5-7B-Instruct'}),
            'model_type': forms.Select(attrs={'class': 'form-select'}),
            'parameter_count': forms.NumberInput(attrs={'class': 'form-control', 'step': 1}),
            'quantization': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'int4, int8, float16...'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'name': 'Уникальное имя в системе (только латиница, цифры, подчёркивание)',
            'display_name': 'Человекочитаемое имя для интерфейса',
            'model_id': 'Hugging Face ID в формате автор/название',
            'parameter_count': 'Количество параметров (например, 7000000000 для 7B)',
            'quantization': 'Тип квантизации (опционально)',
        }

    def clean_model_id(self):
        model_id = self.cleaned_data.get('model_id', '').strip()
        if '/' not in model_id:
            raise forms.ValidationError(_('Hugging Face ID должен быть в формате "author/model_name"'))
        return model_id

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError(_('Имя модели обязательно'))
        if LLMModel.objects.filter(name=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_('Модель с таким именем уже существует'))
        return name


# ============================================================================
# Форма для загрузки модели эмбеддингов с Hugging Face (только для админов)
# ============================================================================
class EmbeddingModelUploadForm(forms.ModelForm):
    """Форма для добавления модели эмбеддингов с Hugging Face Hub"""
    
    class Meta:
        model = EmbeddingModel
        fields = [
            'name', 'display_name', 'model_id', 'embedding_dim',
            'max_tokens', 'is_multilingual', 'license_type',
            'is_default', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'bge_m3'}),
            'display_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'BGE-M3'}),
            'model_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'BAAI/bge-m3'}),
            'embedding_dim': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1024'}),
            'max_tokens': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '8192'}),
            'is_multilingual': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'license_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'MIT, Apache 2.0...'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'name': 'Уникальное имя в системе (только латиница, цифры, подчёркивание)',
            'display_name': 'Человекочитаемое имя для интерфейса',
            'model_id': 'Hugging Face ID в формате автор/название',
            'embedding_dim': 'Размерность выходных векторов',
            'max_tokens': 'Максимальная длина входного текста в токенах',
            'is_multilingual': 'Поддерживает ли модель несколько языков',
            'license_type': 'Тип лицензии',
        }

    def clean_model_id(self):
        model_id = self.cleaned_data.get('model_id', '').strip()
        if '/' not in model_id:
            raise forms.ValidationError(_('Hugging Face ID должен быть в формате "author/model_name"'))
        return model_id

    def clean_name(self):
        name = self.cleaned_data.get('name', '').strip()
        if not name:
            raise forms.ValidationError(_('Имя модели обязательно'))
        if EmbeddingModel.objects.filter(name=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_('Модель с таким именем уже существует'))
        return name

    def clean_embedding_dim(self):
        dim = self.cleaned_data.get('embedding_dim')
        if dim is not None and dim <= 0:
            raise forms.ValidationError(_('Размерность должна быть положительным числом'))
        return dim

    def clean_max_tokens(self):
        max_tokens = self.cleaned_data.get('max_tokens')
        if max_tokens is not None and max_tokens <= 0:
            raise forms.ValidationError(_('Максимальное количество токенов должно быть положительным'))
        return max_tokens