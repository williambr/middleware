# $FreeBSD$

PORTNAME=	freenas-containerd
PORTVERSION=	${PRODUCT_VERSION:C/\-.*//:C/\_.*//}
PORTREVISION=	${REVISION}
CATEGORIES=	freenas
VALID_CATEGORIES+=	freenas

MAINTAINER=	dev@ixsystems.com
COMMENT=	FreeNAS container daemon

RUN_DEPENDS=	\
		${PYTHON_PKGNAMEPREFIX}gevent>0:${PORTSDIR}/devel/py-gevent \
		${PYTHON_PKGNAMEPREFIX}gevent-websocket>0:${PORTSDIR}/www/py-gevent-websocket \
		${PYTHON_PKGNAMEPREFIX}setproctitle>0:${PORTSDIR}/devel/py-setproctitle \

USES=		python
EXTRACT_ONLY=

NO_BUILD=	yes
MAKE_JOBS_UNSAFE= yes
ALL_TARGET=	obj all
WRKSRC=		/usr/middleware_src/containerd

checksum fetch:
	${ECHO_CMD} ${.TARGET} not needed because building direct

do-install:
	${MAKE} -C ${WRKSRC} install PREFIX=${STAGEDIR}${PREFIX} PYTHON=${PYTHON_CMD}

post-install:
	${PYTHON_CMD} -m compileall ${STAGEDIR}${PREFIX}/lib/containerd
	(cd ${STAGEDIR}${PREFIX}/lib/containerd; ${FIND} -E . -type f -regex ".*.pyc?" \
		| ${SED} -e 's,^\./,,g' \
		| ${AWK} '{print length, $$0}' | ${SORT} -rn \
		| ${AWK} '{print "lib/containerd/"$$2 }' >> ${TMPPLIST})

.include <bsd.port.mk>
