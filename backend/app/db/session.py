from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings

engine = create_async_engine(
    str(settings.DATABASE_URL),
    pool_pre_ping=True,
    pool_size=100,
    max_overflow=100,
    pool_recycle=1800,
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
