document.addEventListener('DOMContentLoaded', function() {
    // Accordion functionality for services
    const accordionItems = document.querySelectorAll('.accordion');
    
    accordionItems.forEach(item => {
        const header = item.querySelector('.service-header');
        
        header.addEventListener('click', () => {
            // Close all other accordion items
            accordionItems.forEach(otherItem => {
                if (otherItem !== item) {
                    otherItem.classList.remove('active');
                }
            });
            
            // Toggle current item
            item.classList.toggle('active');
        });
    });
    
    // Client type selection
    const clientTypes = document.querySelectorAll('.client-type');
    
    clientTypes.forEach(type => {
        type.addEventListener('click', () => {
            // Remove active class from all types
            clientTypes.forEach(otherType => {
                otherType.classList.remove('active');
            });
            
            // Add active class to clicked type
            type.classList.add('active');
            
            // Here you could also update the content based on the selected client type
            // For example, change the benefits list or image
        });
    });
    
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            
            const targetId = this.getAttribute('href');
            const targetElement = document.querySelector(targetId);
            
            if (targetElement) {
                window.scrollTo({
                    top: targetElement.offsetTop - 100, // Offset for fixed header
                    behavior: 'smooth'
                });
            }
        });
    });
    
    // Form submission
    const contactForm = document.querySelector('.contact-form');
    
    if (contactForm) {
        contactForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Here you would normally send the form data to a server
            // For this example, we'll just show a success message
            
            const formData = new FormData(contactForm);
            let formValues = {};
            
            for (let [key, value] of formData.entries()) {
                formValues[key] = value;
            }
            
            console.log('Form submitted with values:', formValues);
            
            // Show success message
            contactForm.innerHTML = '<div class="success-message"><h3>Спасибо за вашу заявку!</h3><p>Мы свяжемся с вами в ближайшее время.</p></div>';
        });
    }
    
    // Add animation classes when elements come into view
    const animateOnScroll = function() {
        const elements = document.querySelectorAll('.benefit-card, .service-item, .client-type');
        
        elements.forEach(element => {
            const elementPosition = element.getBoundingClientRect().top;
            const windowHeight = window.innerHeight;
            
            if (elementPosition < windowHeight - 100) {
                element.classList.add('fade-in');
            }
        });
    };
    
    // Run animation check on scroll
    window.addEventListener('scroll', animateOnScroll);
    
    // Run once on page load
    animateOnScroll();
});