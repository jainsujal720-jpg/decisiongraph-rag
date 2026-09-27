from decisiongraph.core.config import Settings


def test_secret_is_not_exposed_in_settings_repr():
    settings = Settings(openai_api_key="super-secret")
    assert "super-secret" not in repr(settings)


def test_embedding_dimension_matches_stage_one_schema():
    settings = Settings()
    assert settings.embedding_dimensions == 1536


def test_cors_origin_configuration_is_explicit_and_split_safely():
    settings = Settings(cors_allow_origins="http://localhost:3000, https://review.example")
    assert settings.allowed_cors_origins == ["http://localhost:3000", "https://review.example"]
