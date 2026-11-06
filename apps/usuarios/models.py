"""Modelo de usuário do JusGestor Hub.

Segue a tabela ``usuario`` do modelo relacional (Figura 3 do artigo):
id, nome, email, senha_hash, perfil, ativo, trocar_senha, criado_em.

Acréscimos documentados em docs/alteracoes-modelo.md:
- ``last_login``: exigido pelo sistema de autenticação do Django;
- ``tentativas_falhas`` e ``bloqueado_ate``: bloqueio de login do RF01.
"""
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class Perfil(models.TextChoices):
    ADM = "ADM", "Administrador"
    ADV = "ADV", "Advogado"
    AST = "AST", "Assistente"


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email):
        return (email or "").strip().lower()

    def create_user(self, email, nome, perfil, password=None, **extra):
        if not email:
            raise ValueError("O e-mail é obrigatório.")
        if perfil not in Perfil.values:
            raise ValueError("Perfil inválido.")
        usuario = self.model(email=self.normalize_email(email), nome=nome, perfil=perfil, **extra)
        # Sem senha informada, a conta fica com senha inutilizável.
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def get_by_natural_key(self, email):
        return self.get(email=self.normalize_email(email))


class Usuario(AbstractBaseUser):
    nome = models.CharField("nome", max_length=150)
    email = models.EmailField("e-mail", max_length=254, unique=True)
    # Coluna "senha_hash" do modelo relacional; o valor é sempre o hash gerado
    # pelo Django (RNF02), nunca a senha em texto.
    password = models.CharField("senha", max_length=255, db_column="senha_hash")
    perfil = models.CharField("perfil", max_length=3, choices=Perfil.choices)
    ativo = models.BooleanField("ativo", default=True)
    trocar_senha = models.BooleanField("trocar senha no próximo acesso", default=True)
    criado_em = models.DateTimeField("criado em", default=timezone.now, editable=False)

    # RF01 — bloqueio após falhas consecutivas.
    tentativas_falhas = models.PositiveSmallIntegerField("tentativas de login com falha", default=0)
    bloqueado_ate = models.DateTimeField("login bloqueado até", null=True, blank=True)

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["nome", "perfil"]

    class Meta:
        db_table = "usuario"
        verbose_name = "usuário"
        verbose_name_plural = "usuários"
        ordering = ["nome"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(perfil__in=Perfil.values),
                name="usuario_perfil_valido",
            ),
            models.UniqueConstraint(Lower("email"), name="usuario_email_unico_ci"),
        ]

    def __str__(self):
        return f"{self.nome} ({self.get_perfil_display()})"

    def save(self, *args, **kwargs):
        self.email = UsuarioManager.normalize_email(self.email)
        super().save(*args, **kwargs)

    # O Django consulta ``is_active`` para impedir o acesso de contas inativas
    # (RF01, RN07). Aqui ele reflete a coluna ``ativo`` do modelo relacional.
    @property
    def is_active(self):
        return self.ativo

    def esta_bloqueado(self, agora=None):
        agora = agora or timezone.now()
        return self.bloqueado_ate is not None and self.bloqueado_ate > agora

    @property
    def e_administrador(self):
        return self.perfil == Perfil.ADM

    @property
    def e_advogado(self):
        return self.perfil == Perfil.ADV

    @property
    def e_assistente(self):
        return self.perfil == Perfil.AST
